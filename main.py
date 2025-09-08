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

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- Config ----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
PUBLIC_URL = os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN is missing")

WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}" if WEBHOOK_SECRET else f"/webhook/{BOT_TOKEN}"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)

# ---------------- Exam Dates ----------------
EXAMS = {
    "تجربی": (jdatetime.datetime(1405, 4, 12, 8, 0), "🧪"),
    "ریاضی": (jdatetime.datetime(1405, 4, 11, 8, 0), "📐"),
    "انسانی": (jdatetime.datetime(1405, 4, 11, 8, 0), "📚"),
    "هنر": (jdatetime.datetime(1405, 4, 12, 14, 30), "🎨"),
}

ALIASES = {
    "tajrobi": "تجربی",
    "riazi": "ریاضی",
    "ensani": "انسانی",
    "honar": "هنر",
}

# ---------------- Helpers ----------------
def to_gregorian(jdt: jdatetime.datetime) -> datetime.datetime:
    return jdt.togregorian()

def now() -> datetime.datetime:
    if ZoneInfo is not None:
        return datetime.datetime.now(tz=ZoneInfo("Asia/Tehran"))
    return datetime.datetime.utcnow()

def countdown_text(jdt: jdatetime.datetime, exam: str, emoji: str) -> str:
    target = to_gregorian(jdt).replace(tzinfo=None)
    current = now().replace(tzinfo=None)
    delta = target - current

    days = delta.days
    seconds = delta.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    date_str = f"{jdt.year}/{jdt.month}/{jdt.day} - ساعت {jdt.hour:02d}:{jdt.minute:02d}"

    if delta.total_seconds() > 0:
        return (
            f"{emoji} شمارش معکوس کنکور «{exam}»\n"
            f"⏳ {days} روز، {hours} ساعت و {minutes} دقیقه مونده!\n"
            f"🗓 تاریخ برگزاری: {date_str}"
        )
    elif -3600*5 < delta.total_seconds() <= 0:  # توی روز آزمون
        return f"🚨 آزمون {exam} همین الان شروع شده! موفق باشی 🌹"
    else:
        return f"✅ آزمون {exam} برگزار شده است."

def build_keyboard() -> dict:
    keyboard = [
        [{"text": "🧪 تجربی"}, {"text": "📐 ریاضی"}],
        [{"text": "📚 انسانی"}, {"text": "🎨 هنر"}],
        [{"text": "🏠 بازگشت به منو"}],
    ]
    return {"keyboard": keyboard, "resize_keyboard": True}

def send_message(chat_id: int, text: str, reply_markup: Optional[dict] = None) -> None:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    try:
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", data=payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"SendMessage error: {e}")

def resolve_exam(text: str) -> Optional[str]:
    t = text.strip().lower().replace("🧪","").replace("📐","").replace("📚","").replace("🎨","").strip()
    if t in EXAMS:
        return t
    if t in ALIASES:
        return ALIASES[t]
    return None

# ---------------- Routes ----------------
@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True)
    if not update:
        return jsonify({"ok": False}), 400

    message = update.get("message") or update.get("edited_message")
    if message:
        chat_id = message["chat"]["id"]
        text = message.get("text") or ""
        if text:
            handle_message(chat_id, text)

    return "OK"

def handle_message(chat_id: int, text: str) -> None:
    text = text.strip()

    if text in ["/start", "شروع", "🏠 بازگشت به منو"]:
        welcome = (
            "🎓 سلام به ربات شمارش معکوس کنکور ۱۴۰۵ خوش اومدی!\n\n"
            "📌 رشته‌ت رو انتخاب کن تا تایمر دقیق رو ببینی ⏳"
        )
        send_message(chat_id, welcome, reply_markup=build_keyboard())
        return

    if text.startswith("/countdown"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            send_message(chat_id, "❌ دستور صحیح: /countdown <رشته>")
            return
        exam_name = parts[1]
    else:
        exam_name = text

    exam = resolve_exam(exam_name)
    if not exam:
        send_message(chat_id, "❓ رشته ناشناخته است. یکی از گزینه‌ها رو انتخاب کن:", reply_markup=build_keyboard())
        return

    jdt, emoji = EXAMS[exam]
    msg = countdown_text(jdt, exam, emoji)
    send_message(chat_id, msg, reply_markup=build_keyboard())

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    if not PUBLIC_URL:
        return jsonify({"ok": False, "error": "PUBLIC_URL not set"}), 400
    webhook_url = f"{PUBLIC_URL}{WEBHOOK_PATH}"
    try:
        r = requests.post(f"{TELEGRAM_API}/setWebhook", data={"url": webhook_url}, timeout=10)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ---------------- Main ----------------
if __name__ == "__main__":
    if PUBLIC_URL:
        try:
            webhook_url = f"{PUBLIC_URL}{WEBHOOK_PATH}"
            r = requests.post(f"{TELEGRAM_API}/setWebhook", data={"url": webhook_url}, timeout=10)
            logger.info(f"Webhook set: {r.text}")
        except Exception as e:
            logger.warning(f"Webhook setup failed: {e}")

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
