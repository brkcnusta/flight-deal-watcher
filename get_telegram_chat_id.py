"""
Kullanım:
1. Telegram'da botunuza gidip /start yazın (ya da herhangi bir mesaj gönderin).
2. Bu scripti çalıştırın: python get_telegram_chat_id.py
3. Bulduğu chat ID'yi .env dosyasındaki TELEGRAM_CHAT_ID'ye yapıştırın.
"""
import os

import requests
from dotenv import load_dotenv

load_dotenv()

token = os.environ["TELEGRAM_BOT_TOKEN"]
resp = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20)
resp.raise_for_status()
updates = resp.json().get("result", [])

if not updates:
    print("Hiç mesaj bulunamadı. Önce Telegram'da botunuza /start yazıp tekrar deneyin.")
else:
    seen = set()
    for u in updates:
        msg = u.get("message") or u.get("channel_post")
        if not msg:
            continue
        chat = msg["chat"]
        key = (chat["id"], chat.get("username") or chat.get("title") or chat.get("first_name"))
        if key not in seen:
            seen.add(key)
            print(f"chat_id={chat['id']}  ({key[1]})")
