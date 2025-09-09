import os
import json
import time
import logging
import jdatetime
import requests
import traceback
from datetime import datetime, timezone
from flask import Flask, request
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

# Load .env
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set in environment")

TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"

# Flask app
app = Flask(__name__)

# Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

# کنکورها
EXAMS = {
    "تجربی": [{"date": jdatetime.datetime(1405, 4, 12, 8, 0), "time": "08:00 صبح"}],
    "ریاضی": [{"date": jdatetime.datetime(1405, 4, 11, 8, 0), "time": "08:00 صبح"}],
    "انسانی": [{"date": jdatetime.datetime(1405, 4, 11, 8, 0), "time": "08:00 صبح"}],
    "هنر":   [{"date": jdatetime.datetime(1405, 4, 12, 14, 30), "time": "14:30 عصر"}],
    "فرهنگیان": [
        {"date": jdatetime.datetime(1405, 2, 17, 8, 0), "time": "08:00 صبح"},
        {"date": jdatetime.datetime(1405, 2, 18, 8, 0), "time": "08:00 صبح"},
    ],
}

# دیتابیس ساده در حافظه
user_study = {}
user_reminders = {}  # {chat_id: {"reminders": [{exam, time}], "step": None, "pending_exam": None}}

# Scheduler
scheduler = BackgroundScheduler()
scheduler.start()

# ارسال پیام
def send_message(chat_id: int, text: str, reply_markup: dict | None = None):
    logger.info(f"📤 Sending message to chat_id={chat_id}: {text[:50]}")
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

    try:
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", data=payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"send_message error: {e}, response: {getattr(resp, 'text', '')}")

# ارسال پیام با دکمه شیشه‌ای
def send_message_inline(chat_id: int, text: str, inline_keyboard: list):
    logger.info(f"📤 Sending inline message to chat_id={chat_id}: {text[:50]}")
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": json.dumps({"inline_keyboard": inline_keyboard}, ensure_ascii=False)
    }
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", data=payload, timeout=10)
    except Exception as e:
        logger.error(f"send_message_inline error: {e}")

# پاسخ به callback_query
def answer_callback_query(callback_query_id, text=""):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = False
    try:
        requests.post(f"{TELEGRAM_API}/answerCallbackQuery", data=payload, timeout=10)
    except Exception as e:
        logger.error(f"answer_callback_query error: {e}")

# بقیه کد بدون تغییر ...
