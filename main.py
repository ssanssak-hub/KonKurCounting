#!/usr/bin/env python3
# coding: utf-8
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

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
PUBLIC_URL = os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")

WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}" if WEBHOOK_SECRET else f"/webhook/{BOT_TOKEN}"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)

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

def to_gregorian(jdate: jdatetime.date) -> datetime.date:
    return jdate.togregorian().date()

def today_date(tehran_timezone: bool = True) -> datetime.date:
    if tehran_timezone and ZoneInfo is not None:
        try:
            return datetime.datetime.now(tz=ZoneInfo("Asia/Tehran")).date()
        except Exception:
            pass
    return datetime.datetime.utcnow().date()

def days_until(jdate: jdatetime.date, today: Optional[datetime.date] = None) -> int:
    target = to_gregorian(jdate)
    today = today or today_date()
    return (target - today).days

def send_message(chat_id: int, text: str, reply_markup: Optional[dict] = None) -> None:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    try:
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", data=payload, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send message: {e}")

def build_main_keyboard() -> dict:
    keyboard = [
        [{"text": "تجربی"}, {"text": "ریاضی"}],
        [{"text": "انسانی"}, {"text": "هنر"}],
    ]
    return {"keyboard": keyboard, "resize_keyboard": True}

def resolve_exam_name(text: str) -> Optional[str]:
    text = text.strip()
    if text in EXAMS:
        return text
    if text.lower() in ALIASES:
        return ALIASES[text.lower()]
    return None

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook() -> str:
    update = request.get_json(force=True, silent=True)
    if not update:
        return jsonify({"ok": False, "error": "Invalid request"}), 400

    message = update.get("message") or update.get("edited_message")
    if message:
        chat_id = message["chat"]["id"]
        text = message.get("text") or message.get("caption")
        if text:
            handle_message(chat_id, text)
        else:
            send_message(chat_id, "فقط متن یا دستور پشتیبانی می‌شود 📄")

    return "OK"

def handle_message(chat_id: int, text: str) -> None:
    text = text.strip()

    if text.startswith("/start") or text.startswith("شروع"):
        start_message = (
            "سلام 👋\n"
            "من ربات روزشمار کنکور هستم.\n"
            "رشته‌ها:\n"
            "• تجربی (12 تیر 1405)\n"
            "• هنر (12 تیر 1405)\n"
            "• ریاضی (11 تیر 1405)\n"
            "• انسانی (11 تیر 1405)\n\n"
            "نام رشته را بفرستید یا از دکمه‌ها استفاده کنید.\n"
            "همچنین می‌توانید از دستور /countdown <رشته> استفاده کنید."
        )
        send_message(chat_id, start_message, reply_markup=build_main_keyboard())
        return

    if text.startswith("/countdown"):
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
            "رشته‌ای شناخته نشد. لطفاً یکی از موارد زیر را ارسال کنید:\nتجربی، ریاضی، انسانی، هنر",
            reply_markup=build_main_keyboard(),
        )
        return

    exam_date = EXAMS[exam]
    days = days_until(exam_date)
    gregorian_date = to_gregorian(exam_date)

    if days > 1:
        message = f"تا کنکور رشته «{exam}» {days} روز مانده.\n(تاریخ: {exam_date.year}/{exam_date.month}/{exam_date.day} - {gregorian_date.isoformat()})"
    elif days == 1:
        message = f"تا کنکور رشته «{exam}» 1 روز مانده!\n(تاریخ: {exam_date.year}/{exam_date.month}/{exam_date.day})"
    elif days == 0:
        message = f"امروز کنکور رشته «{exam}» است! موفق باشید! 🎯"
    else:
        message = f"کنکور رشته «{exam}» گذشته است.\n(تاریخ: {exam_date.year}/{exam_date.month}/{exam_date.day})"

    send_message(chat_id, message)

@app.route("/set_webhook", methods=["GET"])
def set_webhook() -> str:
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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
