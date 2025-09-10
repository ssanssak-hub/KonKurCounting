import os
import logging
import traceback
import datetime as dt
import random
from typing import List, Dict

from flask import Flask, request
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

# ================== تنظیمات پایه ==================
TOKEN = os.getenv("BOT_TOKEN", "توکن_ربات_اینجا")
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
TEHRAN_TZ = pytz.timezone("Asia/Tehran")

# ================== فلـاسک ==================
app = Flask(__name__)

# ================== لاگر ==================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== حافظه داده ==================
user_study: Dict[int, List[dict]] = {}
user_reminders: Dict[int, dict] = {}

# ================== زمانبندی ==================
scheduler = BackgroundScheduler(timezone=TEHRAN_TZ)
scheduler.start()

# ================== پیام‌های انگیزشی ==================
MOTIVATIONS = [
    "🌟 تو می‌تونی موفق بشی!",
    "💪 تلاش امروزت نتیجه فرداست.",
    "📚 هر ساعت مطالعه، یک قدم نزدیک‌تر به هدفت.",
    "🚀 ادامه بده، آینده از آن توست!",
]

# ================== اطلاعات کنکورها ==================
EXAMS = {
    "تجربی": [dt.datetime(2026, 7, 2, 8, 0, tzinfo=TEHRAN_TZ)],
    "ریاضی": [dt.datetime(2026, 7, 2, 8, 0, tzinfo=TEHRAN_TZ)],
    "انسانی": [dt.datetime(2026, 7, 3, 8, 0, tzinfo=TEHRAN_TZ)],
    "هنر": [dt.datetime(2026, 7, 4, 8, 0, tzinfo=TEHRAN_TZ)],
    "فرهنگیان": [
        dt.datetime(2026, 5, 7, 8, 0, tzinfo=TEHRAN_TZ),  # 17 اردیبهشت 1405
        dt.datetime(2026, 5, 8, 8, 0, tzinfo=TEHRAN_TZ),  # 18 اردیبهشت 1405
    ],
}

# ================== توابع کمکی ==================
def send_message(chat_id, text, reply_markup=None):
    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(url, json=payload)

def send_message_inline(chat_id, text, inline_keyboard):
    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {"inline_keyboard": inline_keyboard},
    }
    requests.post(url, json=payload)

def send_answer_callback(callback_query_id, text):
    url = f"{BASE_URL}/answerCallbackQuery"
    requests.post(url, json={"callback_query_id": callback_query_id, "text": text})

def get_countdown(exam_name: str) -> str:
    now = dt.datetime.now(TEHRAN_TZ)
    dates = EXAMS.get(exam_name, [])
    msgs = []
    for d in dates:
        delta = d - now
        days, seconds = delta.days, delta.seconds
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        msgs.append(f"📅 {exam_name} در تاریخ {d.strftime('%Y/%m/%d %H:%M')}\n"
                    f"⏳ مانده: {days} روز، {hours} ساعت، {mins} دقیقه")
    return "\n\n".join(msgs) if msgs else "❌ تاریخ مشخص نشده."

def normalize_time_str(s: str) -> str:
    return s.strip().replace(" ", "").replace("：", ":")

def parse_times_list(text: str) -> List[str]:
    return [normalize_time_str(t) for t in text.split(",") if t.strip()]

# ================== منوها ==================
def main_menu():
    return {
        "keyboard": [
            ["🔎 چند روز تا کنکور؟"],
            ["📖 برنامه‌ریزی"],
            ["🔔 بهم یادآوری کن!"],
        ],
        "resize_keyboard": True,
    }

def exam_menu(include_reminder_manage=False):
    kb = [
        ["🧪 کنکور تجربی", "📐 کنکور ریاضی"],
        ["📚 کنکور انسانی", "🎨 کنکور هنر"],
        ["🏫 کنکور فرهنگیان"],
    ]
    if include_reminder_manage:
        kb.append(["❌ مدیریت یادآوری‌ها", "📅 گزارش روزانه کنکورها"])
    return {"keyboard": kb, "resize_keyboard": True}

def study_menu():
    return {
        "keyboard": [["➕ ثبت مطالعه", "📊 مشاهده پیشرفت"], ["🗑️ حذف مطالعه"], ["⬅️ بازگشت"]],
        "resize_keyboard": True,
    }

def reminder_root_menu():
    return {
        "keyboard": [
            ["📅 گزارش روزانه کنکورها"],
            ["⬅️ بازگشت"],
        ],
        "resize_keyboard": True,
    }

# ================== زمان‌بندی یادآوری ==================
def schedule_reminder(chat_id: int, exam_name: str, time_str: str):
    h, m = map(int, time_str.split(":"))
    job_id = f"rem|{chat_id}|{exam_name}|{time_str}"

    def _send(chat_id=chat_id, exam=exam_name):
        msg = f"🔔 یادآوری کنکور {exam}\n{get_countdown(exam)}\n\n{random.choice(MOTIVATIONS)}"
        send_message(chat_id, msg)

    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(_send, CronTrigger(hour=h, minute=m, timezone=TEHRAN_TZ), id=job_id)
    user_reminders.setdefault(chat_id, {}).setdefault("reminders", []).append({"exam": exam_name, "time": time_str})

# ================== وبهوک ==================
@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    try:
        update = request.get_json()
        if "message" in update:
            chat_id = update["message"]["chat"]["id"]
            text = update["message"].get("text", "")
            send_message(chat_id, f"پیام تستی دریافت شد: {text}", reply_markup=main_menu())
        elif "callback_query" in update:
            cq = update["callback_query"]
            data = cq["data"]
            chat_id = cq["message"]["chat"]["id"]
            callback_query_id = cq["id"]
            send_answer_callback(callback_query_id, f"دریافت شد: {data}")
    except Exception:
        logger.error(f"webhook error: {traceback.format_exc()}")
    return {"ok": True}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
