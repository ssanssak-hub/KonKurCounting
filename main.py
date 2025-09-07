#!/usr/bin/env python3
# coding: utf-8
"""
ربات تلگرامی روزشمار کنکور
"""

import os
import json
import datetime
import logging
from typing import Optional

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:
    ZoneInfo = None

import jdatetime
import requests
from flask import Flask, request, jsonify

# Load .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Config ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
PUBLIC_URL = os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment variable is missing!")

WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}" if WEBHOOK_SECRET else f"/webhook/{BOT_TOKEN}"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)

# --- Exam dates (Jalali calendar) ---
EXAMS = {
    "تجربی": jdatetime.date(1405, 4, 12),
    "هنر": jdatetime.date(1405, 4, 12),
    "ریاضی": jdatetime.date(1405, 4, 11),
    "انسانی": jdatetime.date(1405, 4, 11),
}

ALIASES = {
    "tajrobi": "تجربی",
    "honar": "هنر",
    "riazi": "ریاضی",
    "ensani": "انسانی",
}


# --- Helpers ---
def to_gregorian(jdate: jdatetime.date) -> datetime.date:
    return jdate.togregorian().date()

def today_date() -> datetime.date:
    if ZoneInfo:
        try:
            return datetime.datetime.now(tz=ZoneInfo("Asia/Tehran")).date()
        except Exception:
            pass
    return datetime.datetime.utcnow().date()

def days_until(jdate: jdatetime.date) -> int:
    target = to_gregorian(jdate)
    return (target - today_date()).days

def build_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": "تجربی"}, {"text": "ریاضی"}],
            [{"text": "انسانی"}, {"text": "هنر"}],
        ],
        "resize_keyboard": True,
    }

def send_message(chat_id: int, text: str, with_keyboard=False) -> None:
    """ارسال پیام به تلگرام"""
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if with_keyboard:
        payload["reply_markup"] = json.dumps(build_keyboard(), ensure_ascii=False)

    try:
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", data=payload, timeout=10)
        logger.info(f"📤 پیام به {chat_id}: {text[:40]}... | status={resp.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ خطا در ارسال پیام: {e}")

def resolve_exam_name(text: str) -> Optional[str]:
    t = text.strip().lower()
    if t in EXAMS:
        return t
    if t in ALIASES:
        return ALIASES[t]
    return None

def get_countdown_message(exam: str) -> str:
    exam_date = EXAMS[exam]
    days = days_until(exam_date)
    gregorian = to_gregorian(exam_date)

    if days > 1:
        return f"تا کنکور رشته «{exam}» {days} روز مانده.\n📅 تاریخ: {exam_date} ({gregorian})"
    elif days == 1:
        return f"فردا کنکور رشته «{exam}» است! ⏳"
    elif days == 0:
        return f"امروز روز کنکور رشته «{exam}» است! موفق باشید! 🎯"
    else:
        return f"کنکور رشته «{exam}» گذشته است. 📅 تاریخ: {exam_date} ({gregorian})"


# --- Flask Routes ---
@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook() -> str:
    update = request.get_json(force=True, silent=True)
    if not update:
        return jsonify({"ok": False, "error": "Invalid update"}), 400

    message = update.get("message") or update.get("edited_message")
    if message:
        chat_id = message["chat"]["id"]
        text = message.get("text") or ""
        handle_message(chat_id, text)

    return "OK"

def handle_message(chat_id: int, text: str) -> None:
    logger.info(f"📩 پیام از {chat_id}: {text}")

    if text.startswith("/start") or "منو" in text:
        send_message(chat_id, "سلام! یکی از گزینه‌های زیر رو انتخاب کن:", with_keyboard=True)
        return

    exam_key = resolve_exam_name(text)
    if exam_key:
        send_message(chat_id, get_countdown_message(exam_key))
    else:
        send_message(chat_id, "❓ رشته شناخته نشد. لطفاً یکی از گزینه‌های منو رو انتخاب کنید.", with_keyboard=True)


@app.route("/set_webhook", methods=["GET"])
def set_webhook() -> str:
    if not PUBLIC_URL:
        return jsonify({"ok": False, "error": "PUBLIC_URL not set"}), 400

    webhook_url = f"{PUBLIC_URL}{WEBHOOK_PATH}"
    try:
        resp = requests.post(f"{TELEGRAM_API}/setWebhook", data={"url": webhook_url}, timeout=10)
        result = resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Failed to set webhook: {e}")
        result = {"ok": False, "error": str(e)}

    return jsonify({"setWebhook": webhook_url, "result": result})


# --- Run ---
if __name__ == "__main__":
    if PUBLIC_URL:
        try:
            webhook_url = f"{PUBLIC_URL}{WEBHOOK_PATH}"
            resp = requests.post(f"{TELEGRAM_API}/setWebhook", data={"url": webhook_url}, timeout=10)
            logger.info(f"✅ Webhook set to {webhook_url} | {resp.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ Webhook set failed: {e}")

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
