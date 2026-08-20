import os
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import yaml
from dotenv import load_dotenv

from deal_detector import evaluate
from google_flights_client import cheapest_for_date
from state_store import load_state, route_key, save_state
from telegram_notifier import send_message

ROUTES_PATH = os.path.join(os.path.dirname(__file__), "routes.yaml")
HISTORY_WINDOW = 30
DEFAULT_DATES_PER_RUN = 6
DEFAULT_RECHECK_AFTER_HOURS = 20
REQUEST_DELAY_SECONDS = 1.5


def daterange(start: str, end: str) -> list[str]:
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def google_flights_link(origin: str, destination: str, depart: str, ret: str | None) -> str:
    q = f"Flights from {origin} to {destination} on {depart}"
    if ret:
        q += f" through {ret}"
    return "https://www.google.com/travel/flights?q=" + urllib.parse.quote(q)


def pick_dates_to_check(
    candidate_dates: list[str], known: dict, dates_per_run: int, recheck_after_hours: float
) -> list[str]:
    now = datetime.now(timezone.utc)
    never = datetime.min.replace(tzinfo=timezone.utc)
    stale = []
    for d in candidate_dates:
        info = known.get(d)
        if info is None:
            stale.append((never, d))
            continue
        checked_at = datetime.fromisoformat(info["checked_at"])
        if (now - checked_at).total_seconds() / 3600 >= recheck_after_hours:
            stale.append((checked_at, d))
    stale.sort(key=lambda t: t[0])
    return [d for _, d in stale[:dates_per_run]]


def run() -> None:
    load_dotenv()
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    with open(ROUTES_PATH, "r") as f:
        routes = yaml.safe_load(f)["routes"]

    state = load_state()

    for route in routes:
        key = route_key(route)
        print(f"[{key}] taraniyor...", file=sys.stderr)

        one_way = route["trip_type"] == "one_way"
        trip_length = route.get("trip_length_days") if not one_way else None
        candidate_dates = daterange(route["date_from"], route["date_to"])

        route_state = state["routes"].setdefault(key, {"dates": {}, "history": []})
        known = route_state["dates"]

        to_check = pick_dates_to_check(
            candidate_dates,
            known,
            route.get("dates_per_run", DEFAULT_DATES_PER_RUN),
            route.get("recheck_after_hours", DEFAULT_RECHECK_AFTER_HOURS),
        )

        for depart_date in to_check:
            return_date = None
            if trip_length:
                return_date = (date.fromisoformat(depart_date) + timedelta(days=trip_length)).isoformat()

            result = cheapest_for_date(
                origin=route["origin"],
                destination=route["destination"],
                depart_date=depart_date,
                return_date=return_date,
                adults=route.get("adults", 1),
                currency=route.get("currency", "USD"),
            )
            time.sleep(REQUEST_DELAY_SECONDS)

            if result is None:
                print(f"[{key}] {depart_date}: veri alinamadi, atlaniyor", file=sys.stderr)
                continue

            known[depart_date] = {
                **result,
                "return_date": return_date,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }

        if not known:
            print(f"[{key}] henuz veri yok", file=sys.stderr)
            continue

        best_date, best_info = min(known.items(), key=lambda kv: kv[1]["price"])
        current_price = best_info["price"]

        is_deal, reason = evaluate(
            history_prices=route_state["history"],
            current_price=current_price,
            discount_threshold_pct=route.get("discount_threshold_pct", 15),
            max_price=route.get("max_price"),
        )

        if is_deal:
            link = google_flights_link(route["origin"], route["destination"], best_date, best_info.get("return_date"))
            airlines_str = ", ".join(best_info.get("airlines") or []) or "bilinmiyor"
            dates_str = best_date + (f" -> {best_info['return_date']}" if best_info.get("return_date") else "")
            stops = best_info.get("stops")
            stops_str = "direkt" if stops == 0 else (f"{stops} aktarma" if stops else "bilinmiyor")

            text = (
                f"✈️ <b>Firsat: {route['name']}</b>\n"
                f"Fiyat: <b>{current_price:.0f} {route.get('currency', 'USD')}</b>\n"
                f"Tarih: {dates_str}\n"
                f"Havayolu: {airlines_str} ({stops_str})\n"
                f"Sebep: {reason}\n"
                f"{link}"
            )
            send_message(bot_token, chat_id, text)
            print(f"[{key}] BILDIRIM GONDERILDI: {current_price}", file=sys.stderr)
        else:
            print(f"[{key}] en ucuz {current_price} ({best_date}) - {reason}", file=sys.stderr)

        route_state["history"] = (route_state["history"] + [current_price])[-HISTORY_WINDOW:]

    save_state(state)


if __name__ == "__main__":
    run()
