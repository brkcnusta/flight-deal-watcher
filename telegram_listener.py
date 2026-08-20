import os
import sys

import requests
from dotenv import load_dotenv

import watcher
from state_store import load_state, save_state

PRICE_COMMANDS = {"/fiyat", "fiyat", "/simdi", "simdi", "/kontrol", "kontrol", "/check"}
REPORT_COMMANDS = {"/rapor", "rapor"}


def run() -> None:
    load_dotenv()
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = str(os.environ["TELEGRAM_CHAT_ID"])

    state = load_state()
    last_update_id = state.get("telegram_last_update_id", 0)

    resp = requests.get(
        f"https://api.telegram.org/bot{bot_token}/getUpdates",
        params={"offset": last_update_id + 1, "timeout": 0},
        timeout=20,
    )
    resp.raise_for_status()
    updates = resp.json().get("result", [])

    if not updates:
        print("Yeni mesaj yok.", file=sys.stderr)
        return

    price_triggered = False
    report_triggered = False
    max_update_id = last_update_id
    for u in updates:
        max_update_id = max(max_update_id, u["update_id"])
        msg = u.get("message")
        if not msg:
            continue
        if str(msg["chat"]["id"]) != chat_id:
            continue
        text = (msg.get("text") or "").strip().lower()
        if text in PRICE_COMMANDS:
            price_triggered = True
        elif text in REPORT_COMMANDS:
            report_triggered = True

    state["telegram_last_update_id"] = max_update_id
    save_state(state)

    if price_triggered:
        print("/fiyat algilandi, fiyat kontrolu tetikleniyor.", file=sys.stderr)
        os.environ["FORCE_REPORT"] = "true"
        watcher.run()

    if report_triggered:
        print("/rapor algilandi, tam gecmis gonderiliyor.", file=sys.stderr)
        watcher.send_full_history_report()

    if not price_triggered and not report_triggered:
        print("Yeni mesaj var ama taninan bir komut degil.", file=sys.stderr)


if __name__ == "__main__":
    run()
