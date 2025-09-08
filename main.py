#!/usr/bin/env python3
# coding: utf-8

import os
import json
import datetime
import logging
import time
from typing import Optional

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:
    ZoneInfo = None

import jdatetime
import requests
from flask import Flask, request, jsonify

# Load .env if available
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

# --- Exam dates with exact times ---
EXAMS = {
    "تجربی": (jdatetime.datetime(1405, 4, 12, 8, 0), "08:00 صبح"),
    "هنر": (jdatetime.datetime(1405, 4, 12, 14, 30), "14:30 بعدازظهر"),
    "ریاضی": (jdatetime.datetime(1405, 4, 11, 8, 0), "08:00 صبح"),
    "انسانی": (jdatetime.datetime(1405, 4, 11, 8, 0), "08:00 صبح"),
    "فرهنگیان - روز اول": (jdatetime.datetime(1405, 2, 17, 8, 0), "08:00 صبح"),
    "فرهنگیان - روز دوم": (jdatetime.datetime(1405, 2, 18, 8, 0), "08:00 صبح"),
}

ALIASES = {
    "tajrobi": "تجربی",
    "honar": "هنر",
    "riazi": "ریاضی",
    "ensani": "انسانی",
    "farhangi": "فرهنگیان - روز اول",
}

# --- Memory for study logs ---
study_logs = {}  # {user_id: [(date, lesson, hours)]}

def to_gregorian(jdt: jdatetime.datetime) -> datetime.datetime:
    return jdt.togregorian()

def now_tehran() -> datetime.datetime:
    if ZoneInfo:
        return datetime.datetime.now(ZoneInfo("Asia/Tehran"))
    return datetime.datetime.utcnow()

def countdown(target_jdt: jdatetime.datetime) -> (int, int, int):
    """Return days, hours, minutes left."""
    target = to_gregorian(target_jdt)
    now = now_tehran().replace(tzinfo=None)
    diff = target - now
    if diff.total_seconds() < 0:
        return -1, -1, -1
    days = diff.days
    hours, remainder = divmod(diff.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return days, hours, minutes

def send_message(chat_id: int, text: str, reply_markup: Optional[dict] = None):
    """Send a message with retry if rate-limited (429)."""
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

    try:
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", data=payload, timeout=10)
        if resp.status_code == 429:  # Too Many Requests
            data = resp.json()
            retry_after = data.get("parameters", {}).get("retry_after", 3)
            logger.warning(f"Rate limit hit. Retrying after {retry_after} seconds...")
            time.sleep(retry_after)
            return send_message(chat_id, text, reply_markup)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"send_message error: {e}")

def main_menu() -> dict:
    keyboard = [
        [{"text": "تجربی"}, {"text": "ریاضی"}],
        [{"text": "انسانی"}, {"text": "هنر"}],
        [{"text": "فرهنگیان - روز اول"}, {"text": "فرهنگیان - روز دوم"}],
        [{"text": "📚 برنامه‌ریزی"}],
    ]
    return {"keyboard": keyboard, "resize_keyboard": True}

def study_menu() -> dict:
    keyboard = [
        [{"text": "➕ ثبت مطالعه"}, {"text": "📊 مشاهده پیشرفت"}],
        [{"text": "بازگشت ⬅️"}],
    ]
    return {"keyboard": keyboard, "resize_keyboard": True}

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True)
    if not update:
        return jsonify({"ok": False})

    message = update.get("message")
    if not message:
        return "OK"

    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    handle_message(chat_id, text)
    return "OK"

def handle_message(chat_id: int, text: str):
    user_id = chat_id
    txt = text.strip()

    if txt in ["شروع", "/start"]:
        send_message(chat_id,
                     "سلام 👋\nمن ربات روزشمار کنکور هستم.\nیکی از گزینه‌ها رو انتخاب کن:",
                     reply_markup=main_menu())
        return

    if txt == "📚 برنامه‌ریزی":
        send_message(chat_id, "بخش برنامه‌ریزی 📚", reply_markup=study_menu())
        return

    if txt == "بازگشت ⬅️":
        send_message(chat_id, "منو اصلی:", reply_markup=main_menu())
        return

    # Study features
    if txt.startswith("➕ ثبت مطالعه"):
        send_message(chat_id, "لطفاً به فرمت زیر بفرست:\n<نام درس> <ساعت مطالعه>\nمثال: ریاضی 2.5")
        return

    if " " in txt:
        parts = txt.split()
        if len(parts) == 2:
            lesson, hours_str = parts
            try:
                hours = float(hours_str)
                today = now_tehran().date()
                study_logs.setdefault(user_id, []).append((today, lesson, hours))
                send_message(chat_id, f"✅ ثبت شد: {lesson} - {hours} ساعت")
                return
            except ValueError:
                pass

    if txt == "📊 مشاهده پیشرفت":
        logs = study_logs.get(user_id, [])
        if not logs:
            send_message(chat_id, "هنوز مطالعه‌ای ثبت نکردی.")
            return
        today = now_tehran().date()
        week_ago = today - datetime.timedelta(days=7)
        total_week = sum(h for d, _, h in logs if d >= week_ago)
        total_prev = sum(h for d, _, h in logs if week_ago - datetime.timedelta(days=7) <= d < week_ago)
        diff = total_week - total_prev
        trend = "📈 پیشرفت" if diff > 0 else "📉 پسرفت" if diff < 0 else "➖ بدون تغییر"
        send_message(chat_id,
                     f"مطالعه 7 روز اخیر: {total_week:.1f} ساعت\n"
                     f"هفته قبل‌تر: {total_prev:.1f} ساعت\n"
                     f"وضعیت: {trend}")
        return

    # Exams
    exam = ALIASES.get(txt.lower(), txt)
    if exam in EXAMS:
        exam_jdt, start_time = EXAMS[exam]
        d, h, m = countdown(exam_jdt)
        if d >= 0:
            send_message(chat_id,
                         f"⏳ تا کنکور «{exam}» {d} روز و {h} ساعت و {m} دقیقه مونده.\n"
                         f"🕗 ساعت شروع: {start_time}")
        else:
            send_message(chat_id, f"کنکور «{exam}» برگزار شده است.")
        return

    # Default fallback
    send_message(chat_id, "❓ دستور ناشناخته. از منو استفاده کن.", reply_markup=main_menu())

@app.route("/set_webhook")
def set_webhook():
    if not PUBLIC_URL:
        return jsonify({"ok": False, "error": "PUBLIC_URL not set"})
    webhook_url = f"{PUBLIC_URL}{WEBHOOK_PATH}"
    try:
        r = requests.post(f"{TELEGRAM_API}/setWebhook", data={"url": webhook_url}, timeout=10)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

if __name__ == "__main__":
    if PUBLIC_URL:
        try:
            webhook_url = f"{PUBLIC_URL}{WEBHOOK_PATH}"
            requests.post(f"{TELEGRAM_API}/setWebhook", data={"url": webhook_url}, timeout=10)
        except Exception as e:
            logger.warning(f"Webhook set error: {e}")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
