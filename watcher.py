import os
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import yaml
from dotenv import load_dotenv

from chart_generator import build_trend_chart
from deal_detector import evaluate
from google_flights_client import cheapest_for_date
from state_store import load_state, route_key, save_state
from telegram_notifier import send_message, send_photo

ROUTES_PATH = os.path.join(os.path.dirname(__file__), "routes.yaml")
CHART_PATH = os.path.join(os.path.dirname(__file__), "trend_chart.png")
HISTORY_WINDOW = 60
DEFAULT_DATES_PER_RUN = 6
DEFAULT_RECHECK_AFTER_HOURS = 20
REQUEST_DELAY_SECONDS = 1.5
FAILURE_ALERT_THRESHOLD = 3


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


def recent_prices(history: list[dict], days: int) -> list[float]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = [h["price"] for h in history if datetime.fromisoformat(h["checked_at"]) >= cutoff]
    return recent or [h["price"] for h in history]


def run() -> None:
    load_dotenv()
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    force_report = os.environ.get("FORCE_REPORT", "").lower() == "true"
    weekly_report = os.environ.get("WEEKLY_REPORT", "").lower() == "true"

    with open(ROUTES_PATH, "r") as f:
        routes = yaml.safe_load(f)["routes"]

    state = load_state()
    report_lines = []
    weekly_lines = []
    chart_input = {}

    for route in routes:
        key = route_key(route)
        print(f"[{key}] taraniyor...", file=sys.stderr)

        one_way = route["trip_type"] == "one_way"
        trip_length = route.get("trip_length_days") if not one_way else None
        candidate_dates = daterange(route["date_from"], route["date_to"])

        route_state = state["routes"].setdefault(
            key, {"dates": {}, "history": [], "consecutive_failures": 0, "failure_alerted": False}
        )
        known = route_state["dates"]

        to_check = pick_dates_to_check(
            candidate_dates,
            known,
            route.get("dates_per_run", DEFAULT_DATES_PER_RUN),
            route.get("recheck_after_hours", DEFAULT_RECHECK_AFTER_HOURS),
        )

        fetched_this_run = 0
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
                nonstop_only=route.get("nonstop_only", False),
            )
            time.sleep(REQUEST_DELAY_SECONDS)

            if result is None:
                print(f"[{key}] {depart_date}: veri alinamadi, atlaniyor", file=sys.stderr)
                continue

            fetched_this_run += 1
            known[depart_date] = {
                **result,
                "return_date": return_date,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }

        if to_check:
            if fetched_this_run == 0:
                route_state["consecutive_failures"] = route_state.get("consecutive_failures", 0) + 1
            else:
                route_state["consecutive_failures"] = 0
                route_state["failure_alerted"] = False

        if (
            route_state.get("consecutive_failures", 0) >= FAILURE_ALERT_THRESHOLD
            and not route_state.get("failure_alerted", False)
        ):
            send_message(
                bot_token,
                chat_id,
                f"⚠️ <b>Sistem uyarisi: {route['name']}</b>\n"
                f"Art arda {route_state['consecutive_failures']} kontrolde veri alinamadi. "
                f"Google Flights sorgusu bozulmus olabilir, kontrol edilmesi gerekiyor.",
            )
            route_state["failure_alerted"] = True
            print(f"[{key}] HATA BILDIRIMI GONDERILDI", file=sys.stderr)

        if not known:
            print(f"[{key}] henuz veri yok", file=sys.stderr)
            continue

        best_date, best_info = min(known.items(), key=lambda kv: kv[1]["price"])
        current_price = best_info["price"]

        history_prices = [h["price"] for h in route_state["history"]]
        is_deal, reason = evaluate(
            history_prices=history_prices,
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

        if force_report:
            airlines_str = ", ".join(best_info.get("airlines") or []) or "bilinmiyor"
            dates_str = best_date + (f" -> {best_info['return_date']}" if best_info.get("return_date") else "")
            report_lines.append(
                f"{route['name']}: <b>{current_price:.0f} {route.get('currency', 'USD')}</b> "
                f"({airlines_str}, {dates_str})"
            )

        route_state["history"] = (
            route_state["history"]
            + [{"price": current_price, "checked_at": datetime.now(timezone.utc).isoformat()}]
        )[-HISTORY_WINDOW:]

        if weekly_report:
            week_prices = recent_prices(route_state["history"], days=7)
            weekly_lines.append(
                f"{route['name']}: simdi <b>{current_price:.0f}</b>, "
                f"bu hafta min {min(week_prices):.0f} / maks {max(week_prices):.0f} / "
                f"ort {sum(week_prices) / len(week_prices):.0f} {route.get('currency', 'USD')}"
            )
            chart_input[route["name"]] = {"history": route_state["history"], "currency": route.get("currency", "USD")}

    if force_report and report_lines:
        text = "✈️ <b>Güncel Fiyat Raporu</b>\n\n" + "\n".join(report_lines)
        send_message(bot_token, chat_id, text)
        print("Manuel rapor Telegram'a gonderildi.", file=sys.stderr)

    if weekly_report and weekly_lines:
        caption = "📊 <b>Haftalik Ozet</b>\n\n" + "\n".join(weekly_lines)
        if build_trend_chart(chart_input, CHART_PATH):
            send_photo(bot_token, chat_id, CHART_PATH, caption=caption)
        else:
            send_message(bot_token, chat_id, caption)
        print("Haftalik ozet Telegram'a gonderildi.", file=sys.stderr)

    save_state(state)


def send_full_history_report() -> None:
    """Send one Telegram message per route listing every recorded price check."""
    load_dotenv()
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    istanbul = timezone(timedelta(hours=3))

    with open(ROUTES_PATH, "r") as f:
        routes = yaml.safe_load(f)["routes"]

    state = load_state()

    for route in routes:
        key = route_key(route)
        route_state = state["routes"].get(key)
        currency = route.get("currency", "USD")

        if not route_state or not route_state.get("history"):
            send_message(bot_token, chat_id, f"📋 <b>{route['name']}</b>\n\nHenuz veri yok.")
            time.sleep(0.5)
            continue

        lines = []
        for h in route_state["history"]:
            local_dt = datetime.fromisoformat(h["checked_at"]).astimezone(istanbul)
            lines.append(f"{local_dt.strftime('%d.%m %H:%M')} - {h['price']:.0f} {currency}")

        text = f"📋 <b>{route['name']} - Gecmis Fiyatlar</b>\n\n" + "\n".join(lines)
        send_message(bot_token, chat_id, text)
        time.sleep(0.5)

    print("Tam gecmis raporu Telegram'a gonderildi.", file=sys.stderr)


if __name__ == "__main__":
    run()
