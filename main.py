#!/usr/bin/env python3
# coding: utf-8
"""
ربات تلگرامی روزشمار کنکور (با شمارشگر دقیق تا ساعت و دقیقه)
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
from flask import Flask, request, abort, jsonify

# Load .env file if it exists (for local development)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration from environment variables (required)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
PUBLIC_URL = os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")  # Optional: for webhook security

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")

# Webhook path (use secret if available, otherwise use token)
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}" if WEBHOOK_SECRET else f"/webhook/{BOT_TOKEN}"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)

# --- Exam dates (Jalali datetime + time) ---
EXAMS = {
    "تجربی": jdatetime.datetime(1405, 4, 12, 8, 0),   # 12 تیر 1405 - 08:00
    "ریاضی": jdatetime.datetime(1405, 4, 11, 8, 0),   # 11 تیر 1405 - 08:00
    "انسانی": jdatetime.datetime(1405, 4, 11, 8, 0),  # 11 تیر 1405 - 08:00
    "هنر": jdatetime.datetime(1405, 4, 12, 14, 30),   # 12 تیر 1405 - 14:30
}

ALIASES = {
    "tajrobi": "تجربی",
    "honar": "هنر",
    "riazi": "ریاضی",
    "ensani": "انسانی",
}

def to_gregorian(jdt: jdatetime.datetime) -> datetime.datetime:
    """Convert Jalali datetime to Gregorian datetime."""
    return jdt.togregorian()

def now_datetime(tehran_timezone: bool = True) -> datetime.datetime:
    """Get current datetime."""
    if tehran_timezone and ZoneInfo is not None:
        try:
            return datetime.datetime.now(tz=ZoneInfo("Asia/Tehran"))
        except Exception:
            pass  # fallback
    return datetime.datetime.utcnow()

def time_until(jdt: jdatetime.datetime, now: Optional[datetime.datetime] = None) -> tuple[int,int,int,int]:
    """Return days, hours, minutes, seconds until the given Jalali datetime."""
    target = to_gregorian(jdt)
    now = now or now_datetime()
    delta = target - now
    if delta.total_seconds() < 0:
        return (-1, 0, 0, 0)
    days = delta.days
    seconds = delta.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return (days, hours, minutes, secs)

def send_message(chat_id: int, text: str, reply_markup: Optional[dict] = None) -> None:
    """Send a message to Telegram."""
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    try:
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", data=payload, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send message: {e}")

def build_main_keyboard() -> dict:
    """Build the main keyboard for the bot."""
    keyboard = [
        [{"text": "تجربی"}, {"text": "ریاضی"}],
        [{"text": "انسانی"}, {"text": "هنر"}],
    ]
    return {"keyboard": keyboard, "resize_keyboard": True}

def resolve_exam_name(text: str) -> Optional[str]:
    """Resolve exam name from user input."""
    text = text.strip().lower()
    if text in EXAMS:
        return text
    if text in ALIASES:
        return ALIASES[text]
    return None

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook() -> str:
    """Handle Telegram webhook updates."""
    update = request.get_json(force=True, silent=True)
    if not update:
        return jsonify({"ok": False, "error": "Invalid request"}), 400

    message = update.get("message") or update.get("edited_message")
    if message:
        chat_id = message["chat"]["id"]
        text = message.get("text") or message.get("caption") or ""
        if text:
            handle_message(chat_id, text)

    return "OK"

def handle_message(chat_id: int, text: str) -> None:
    """Handle incoming messages."""
    text = text.strip()
    lower_text = text.lower()

    if lower_text.startswith("/start") or lower_text.startswith("شروع"):
        start_message = (
            "سلام 👋\n"
            "من ربات روزشمار کنکور هستم.\n"
            "📅 رشته‌ها:\n"
            "• تجربی (12 تیر 1405 - 08:00)\n"
            "• هنر (12 تیر 1405 - 14:30)\n"
            "• ریاضی (11 تیر 1405 - 08:00)\n"
            "• انسانی (11 تیر 1405 - 08:00)\n\n"
            "نام رشته را بفرستید یا از دکمه‌ها استفاده کنید.\n"
            "همچنین می‌توانید از دستور /countdown <رشته> استفاده کنید."
        )
        send_message(chat_id, start_message, reply_markup=build_main_keyboard())
        return

    if lower_text.startswith("/countdown"):
        parts = text.split(maxsplit=1)
        if len(parts) == 1:
            send_message(chat_id, "دستور صحیح: /countdown <تجربی|ریاضی|انسانی|هنر>")
            return
        exam_name = parts[1].strip()
    else:
        exam_name = text

    exam = resolve_exam_name(exam_name)
    if not exam:
        send_message(
            chat_id,
            "❌ رشته‌ای شناخته نشد. لطفاً یکی از موارد زیر را ارسال کنید:\nتجربی، ریاضی، انسانی، هنر",
            reply_markup=build_main_keyboard(),
        )
        return

    exam_datetime = EXAMS[exam]
    days, hours, minutes, secs = time_until(exam_datetime)

    gregorian_date = to_gregorian(exam_datetime)
    date_str = f"{exam_datetime.year}/{exam_datetime.month}/{exam_datetime.day} - {exam_datetime.hour:02d}:{exam_datetime.minute:02d}"

    if days >= 0:
        message = (
            f"⏳ تا کنکور رشته «{exam}» {days} روز و {hours} ساعت و {minutes} دقیقه مانده.\n"
            f"(تاریخ: {date_str} - {gregorian_date.strftime('%Y-%m-%d %H:%M')})"
        )
    else:
        message = f"✅ کنکور رشته «{exam}» برگزار شده است.\n(تاریخ: {date_str})"

    send_message(chat_id, message)

@app.route("/set_webhook", methods=["GET"])
def set_webhook() -> str:
    """Set the Telegram webhook."""
    if not PUBLIC_URL:
        return jsonify({"ok": False, "error": "PUBLIC_URL is not set"}), 400

    webhook_url = f"{PUBLIC_URL}{WEBHOOK_PATH}"
    try:
        response = requests.post(f"{TELEGRAM_API}/setWebhook", data={"url": webhook_url}, timeout=10)
        result = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to set webhook: {e}")
        result = {"ok": False, "error": str(e)}

    return jsonify({"setWebhook": webhook_url, "result": result})

if __name__ == "__main__":
    # Attempt to set webhook on startup (if PUBLIC_URL is available)
    if PUBLIC_URL:
        try:
            webhook_url = f"{PUBLIC_URL}{WEBHOOK_PATH}"
            response = requests.post(f"{TELEGRAM_API}/setWebhook", data={"url": webhook_url}, timeout=10)
            response.raise_for_status()
            logger.info(f"Webhook set to {webhook_url}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to set webhook on startup: {e}")

    # Run the Flask app
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
