import os
import json
import time
import logging
import jdatetime
import requests
import traceback
import re
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
user_reminders = {}  # {chat_id: {"reminders": [{exam, time}], "step": None|"choose_exam"|"set_time", "pending_exam": str|None}}

# Scheduler
scheduler = BackgroundScheduler()
scheduler.start()

# --- Utilities ---
# تبدیل اعداد فارسی/عربی به انگلیسی و نرمال‌سازی ساعت
_DIGIT_MAP = str.maketrans({
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
})

_COLON_ALTS = ["؛", "،", "﹕", "：", "٫", "·", "٬"]
_HIDDEN_CHARS = ["\u200f", "\u200e", "\u202a", "\u202b", "\u202c", "\u2066", "\u2067", "\u2068", "\u2069", "\ufeff", "\u200d"]

_TIME_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")

def normalize_time_input(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.translate(_DIGIT_MAP)
    for ch in _COLON_ALTS:
        s = s.replace(ch, ":")
    for ch in _HIDDEN_CHARS:
        s = s.replace(ch, "")
    return s.strip()

def parse_time_to_hour_min(s: str):
    s = normalize_time_input(s)
    logger.info(f"⏱ Parsing time input: {repr(s)}")
    if not _TIME_RE.match(s):
        raise ValueError(f"bad time format: {s}")
    hour_str, min_str = s.split(":", 1)
    hour = int(hour_str)
    minute = int(min_str)
    return hour, minute, s

# ارسال پیام
def send_message(chat_id: int, text: str, reply_markup: dict | None = None):
    logger.info(f"📤 Sending message to chat_id={chat_id}: {text[:80]}")
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
    logger.info(f"📤 Sending inline message to chat_id={chat_id}: {text[:80]}")
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

# کیبورد اصلی
def main_menu():
    return {
        "keyboard": [
            [{"text": "🔎 چند روز تا کنکور؟"}],
            [{"text": "📖 برنامه‌ریزی"}],
            [{"text": "🔔 بهم یادآوری کن!"}],
        ],
        "resize_keyboard": True,
    }

# کیبورد انتخاب کنکور برای شمارش یا یادآوری
def exam_menu(include_reminder_manage=False):
    keyboard = [
        [{"text": "🧪 کنکور تجربی"}, {"text": "📐 کنکور ریاضی"}],
        [{"text": "📚 کنکور انسانی"}, {"text": "🎨 کنکور هنر"}],
        [{"text": "🏫 کنکور فرهنگیان"}],
    ]
    if include_reminder_manage:
        keyboard.append([{"text": "❌ مدیریت یادآوری‌ها"}])
    keyboard.append([{"text": "⬅️ بازگشت"}])
    return {"keyboard": keyboard, "resize_keyboard": True}

# کیبورد برنامه‌ریزی
def study_menu():
    return {
        "keyboard": [
            [{"text": "➕ ثبت مطالعه"}, {"text": "📊 مشاهده پیشرفت"}],
            [{"text": "🗑️ حذف مطالعه"}],
            [{"text": "⬅️ بازگشت"}],
        ],
        "resize_keyboard": True,
    }

# محاسبه تایمر
def get_countdown(exam_name: str):
    exams = EXAMS[exam_name]
    results = []
    for exam in exams:
        now = datetime.now(timezone.utc)
        exam_g = exam["date"].togregorian().replace(tzinfo=timezone.utc)
        diff = exam_g - now

        if diff.total_seconds() <= 0:
            results.append(f"✅ کنکور {exam_name} در تاریخ {exam['date'].strftime('%Y/%m/%d')} برگزار شده!")
        else:
            days, remainder = divmod(int(diff.total_seconds()), 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, _ = divmod(remainder, 60)

            results.append(
                f"⏳ کنکور <b>{exam_name}</b>\n"
                f"📅 تاریخ: {exam['date'].strftime('%d %B %Y')} (شمسی: {exam['date']})\n"
                f"🕗 ساعت شروع: {exam['time']}\n"
                f"⌛ باقی‌مانده: {days} روز، {hours} ساعت و {minutes} دقیقه\n"
            )
    return "\n".join(results)

# ایجاد یادآوری با نرمال‌سازی ورودی زمان
def schedule_reminder(chat_id: int, exam_name: str, reminder_time: str):
    hour, minute, normalized = parse_time_to_hour_min(reminder_time)
    logger.info(f"⏰ Scheduling reminder for chat_id={chat_id}, exam={exam_name}, time={normalized} -> {hour:02d}:{minute:02d}")

    def job():
        send_message(chat_id, f"🔔 یادآوری روزانه\n\n{get_countdown(exam_name)}")

    job_id = f"reminder_{chat_id}_{exam_name}"
    scheduler.add_job(job, "cron", hour=hour, minute=minute, id=job_id, replace_existing=True)

    if chat_id not in user_reminders:
        user_reminders[chat_id] = {"reminders": [], "step": None, "pending_exam": None}

    # جلوگیری از یادآوری تکراری
    existing = user_reminders[chat_id]["reminders"]
    for r in existing:
        if r["exam"] == exam_name:
            r["time"] = f"{hour:02d}:{minute:02d}"
            break
    else:
        existing.append({"exam": exam_name, "time": f"{hour:02d}:{minute:02d}"})

# حذف یادآوری
def remove_reminder(chat_id: int, exam_name: str):
    job_id = f"reminder_{chat_id}_{exam_name}"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    if chat_id in user_reminders:
        user_reminders[chat_id]["reminders"] = [r for r in user_reminders[chat_id]["reminders"] if r["exam"] != exam_name]

# هندل پیام‌ها
def handle_message(chat_id: int, text: str):
    if text in ["شروع", "/start"]:
        send_message(chat_id, "سلام 👋 یک گزینه رو انتخاب کن:", reply_markup=main_menu())

    elif text == "🔎 چند روز تا کنکور؟":
        send_message(chat_id, "یک کنکور رو انتخاب کن:", reply_markup=exam_menu())

    elif text == "📖 برنامه‌ریزی":
        send_message(chat_id, "📖 بخش برنامه‌ریزی:", reply_markup=study_menu())

    elif text == "🔔 بهم یادآوری کن!":
        send_message(chat_id, "برای کدوم کنکور می‌خوای یادآوری تنظیم کنی یا مدیریت کنی؟", reply_markup=exam_menu(include_reminder_manage=True))
        if chat_id not in user_reminders:
            user_reminders[chat_id] = {"reminders": [], "step": None, "pending_exam": None}
        user_reminders[chat_id]["step"] = "choose_exam"

    elif text == "❌ مدیریت یادآوری‌ها":
        reminders = user_reminders.get(chat_id, {}).get("reminders", [])
        if not reminders:
            send_message(chat_id, "📭 هیچ یادآوری فعالی نداری.")
        else:
            for r in reminders:
                msg = f"🔔 کنکور {r['exam']} – ساعت {r['time']}"
                inline_kb = [[{"text": "❌ حذف", "callback_data": f"remdel|{r['exam']}"}]]
                send_message_inline(chat_id, msg, inline_kb)

    elif text in ["🧪 کنکور تجربی", "📐 کنکور ریاضی", "📚 کنکور انسانی", "🎨 کنکور هنر", "🏫 کنکور فرهنگیان"]:
        exam_name = text.split()[-1]

        if user_reminders.get(chat_id, {}).get("step") == "choose_exam":
            # حالت یادآوری
            user_reminders[chat_id]["pending_exam"] = exam_name
            user_reminders[chat_id]["step"] = "set_time"
            send_message(chat_id,
                f"⏰ لطفاً ساعت یادآوری روزانه برای کنکور {exam_name} رو وارد کن.\n"
                f"فرمت باید 24 ساعته باشه (HH:MM).\n\n"
                f"مثال‌ها:\n20:00 → ساعت 8 شب\n07:30 → ساعت 7 و نیم صبح\n\n"
                f"نکته: می‌تونی از اعداد فارسی هم استفاده کنی (مثلاً ۰۷:۳۰)."
            )
        else:
            # حالت شمارش معکوس
            countdown = get_countdown(exam_name)
            send_message(chat_id, countdown)

    elif chat_id in user_reminders and user_reminders[chat_id].get("step") == "set_time":
        if text == "⬅️ بازگشت":
            user_reminders[chat_id]["step"] = None
            user_reminders[chat_id]["pending_exam"] = None
            send_message(chat_id, "↩️ بازگشتی به منوی اصلی:", reply_markup=main_menu())
        else:
            try:
                reminder_time = text.strip()
                exam_name = user_reminders[chat_id]["pending_exam"]
                schedule_reminder(chat_id, exam_name, reminder_time)
                user_reminders[chat_id]["step"] = None
                user_reminders[chat_id]["pending_exam"] = None
                normalized = normalize_time_input(reminder_time)
                send_message(chat_id, f"✅ یادآوری برای کنکور {exam_name} هر روز در ساعت {normalized} تنظیم شد.")
            except Exception as e:
                logger.error(f"reminder error: {traceback.format_exc()}")
                send_message(chat_id, "⚠️ فرمت ساعت درست نیست. لطفاً دوباره وارد کن (مثال: 20:00 یا ۰۷:۳۰)")

    elif text == "➕ ثبت مطالعه":
        send_message(
            chat_id,
            "📚 لطفاً اطلاعات مطالعه را به این شکل وارد کنید:\n\n"
            "نام درس، ساعت شروع (hh:mm)، ساعت پایان (hh:mm)، مدت (ساعت)\n\n"
            "مثال:\nریاضی، 14:00، 16:00، 2"
        )

    elif text == "📊 مشاهده پیشرفت":
        logs = user_study.get(chat_id, [])
        if not logs:
            send_message(chat_id, "📭 هنوز مطالعه‌ای ثبت نکردی.")
        else:
            total = sum(entry["duration"] for entry in logs)
            details = "\n".join(
                f"• {e['subject']} | {e['start']} تا {e['end']} | {e['duration']} ساعت"
                for e in logs
            )
            send_message(chat_id, f"📊 مجموع مطالعه: {total} ساعت\n\n{details}")

    elif text == "🗑️ حذف مطالعه":
        logs = user_study.get(chat_id, [])
        if not logs:
            send_message(chat_id, "📭 چیزی برای حذف وجود نداره.")
        else:
            for idx, e in enumerate(logs):
                msg = f"• {e['subject']} | {e['start']} تا {e['end']} | {e['duration']} ساعت"
                inline_kb = [[{"text": "❌ حذف", "callback_data": f"delete_{idx}"}]]
                send_message_inline(chat_id, msg, inline_kb)

    elif text == "⬅️ بازگشت":
        send_message(chat_id, "↩️ بازگشتی به منوی اصلی:", reply_markup=main_menu())

    else:
        try:
            parts = [p.strip() for p in text.split("،")]
            if len(parts) == 4:
                subject, start_time, end_time, duration = parts
                duration = float(duration)
                if chat_id not in user_study:
                    user_study[chat_id] = []
                user_study[chat_id].append(
                    {"subject": subject, "start": start_time, "end": end_time, "duration": duration}
                )
                send_message(chat_id, f"✅ مطالعه {subject} از {start_time} تا {end_time} به مدت {duration} ساعت ثبت شد.")
