import os
import json
import time
import logging
import jdatetime
import requests
import sqlite3
import atexit
import pytz
from datetime import datetime
from typing import Optional, Dict
from flask import Flask, request
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import contextmanager

# Load .env
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set in environment")

TELEGRAM_API = f"https://api.telegram.org/bot{TOKEN}"

# Flask app
app = Flask(__name__)

# Logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
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

# زمان ایران
IRAN_TZ = pytz.timezone('Asia/Tehran')

# مدیریت دیتابیس
DB_FILE = "bot_data.db"

def init_db():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            chat_id INTEGER PRIMARY KEY,
            exam TEXT,
            time TEXT
        )
        ''')

        conn.commit()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    finally:
        conn.close()

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# مقداردهی اولیه دیتابیس
init_db()
atexit.register(lambda: logger.info("🤖 Bot shutting down..."))

# ارسال پیام
def send_message(chat_id: int, text: str, reply_markup: Optional[Dict] = None) -> Optional[int]:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

    try:
        resp = requests.post(f"{TELEGRAM_API}/sendMessage", data=payload, timeout=10)
        resp.raise_for_status()
        return resp.json().get('result', {}).get('message_id')
    except Exception as e:
        logger.error(f"send_message error: {e}")
        return None

# محاسبه شمارش معکوس
def get_countdown(exam_name: str) -> str:
    exams = EXAMS[exam_name]
    results = []
    for exam in exams:
        now = jdatetime.datetime.now()
        exam_date = exam["date"]
        if exam_date < now:
            results.append(f"✅ کنکور {exam_name} در تاریخ {exam_date.strftime('%Y/%m/%d')} برگزار شده!")
        else:
            diff = exam_date - now
            days = diff.days
            hours = diff.seconds // 3600
            minutes = (diff.seconds % 3600) // 60
            results.append(
                f"⏳ کنکور <b>{exam_name}</b>\n"
                f"📅 تاریخ: {exam_date.strftime('%d %B %Y')}\n"
                f"🕗 ساعت شروع: {exam['time']}\n"
                f"⌛ باقی‌مانده: {days} روز، {hours} ساعت و {minutes} دقیقه\n"
            )
    return "\n".join(results)

# دریافت زمان ایران
def get_iran_time() -> str:
    try:
        iran_time = datetime.now(IRAN_TZ)
        return iran_time.strftime("%H:%M")
    except Exception as e:
        logger.error(f"Error getting Iran time: {e}")
        return datetime.now().strftime("%H:%M")

# منوی اصلی
def main_menu():
    return {
        "keyboard": [
            [{"text": "🔎 چند روز تا کنکور؟"}],
            [{"text": "📖 برنامه‌ریزی"}],
            [{"text": "⏰ تنظیم یادآوری"}],
            [{"text": "❌ حذف یادآوری"}],
            [{"text": "🗑️ حذف اطلاعات"}],
            [{"text": "🔄 ریستارت ربات"}],
            [{"text": "📢 عضویت در کانال"}],
        ],
        "resize_keyboard": True,
    }

# انتخاب کنکور
def exam_menu():
    return {
        "keyboard": [
            [{"text": "🧪 کنکور تجربی"}, {"text": "📐 کنکور ریاضی"}],
            [{"text": "📚 کنکور انسانی"}, {"text": "🎨 کنکور هنر"}],
            [{"text": "🏫 کنکور فرهنگیان"}],
            [{"text": "⬅️ بازگشت"}],
        ],
        "resize_keyboard": True,
    }

# ذخیره یادآوری
def save_reminder(chat_id, exam, time_str):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO reminders (chat_id, exam, time) VALUES (?, ?, ?)",
                           (chat_id, exam, time_str))
            conn.commit()
        logger.info(f"✅ Reminder saved for {chat_id}: {exam} at {time_str}")
    except Exception as e:
        logger.error(f"Save reminder error: {e}")

# حذف یادآوری
def delete_reminder(chat_id):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM reminders WHERE chat_id=?", (chat_id,))
            conn.commit()
        logger.info(f"✅ Reminder deleted for {chat_id}")
    except Exception as e:
        logger.error(f"Delete reminder error: {e}")

# ارسال یادآوری‌ها
def send_reminders():
    try:
        now_iran = get_iran_time()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM reminders")
            rows = cursor.fetchall()
            for row in rows:
                if row["time"] == now_iran:
                    exam = row["exam"]
                    chat_id = row["chat_id"]
                    send_message(chat_id, f"⏰ یادآوری امروز:\n\n{get_countdown(exam)}")
                    time.sleep(0.5)
    except Exception as e:
        logger.error(f"send_reminders error: {e}")

# هندل پیام‌ها
waiting_exam = {}
waiting_time = {}

def handle_message(chat_id: int, user_id: int, text: str):
    global waiting_exam, waiting_time

    if chat_id in waiting_exam:
        exam = text.replace("کنکور ", "").strip()
        if exam in EXAMS:
            waiting_time[chat_id] = exam
            del waiting_exam[chat_id]
            send_message(chat_id, "⏰ لطفاً ساعت یادآوری را وارد کنید (مثال: 14:30):")
        else:
            send_message(chat_id, "❌ لطفاً یک کنکور معتبر انتخاب کنید.", reply_markup=exam_menu())
        return

    if chat_id in waiting_time:
        exam = waiting_time[chat_id]
        save_reminder(chat_id, exam, text.strip())
        del waiting_time[chat_id]
        send_message(chat_id, f"✅ یادآوری برای کنکور {exam} در ساعت {text.strip()} تنظیم شد.", reply_markup=main_menu())
        return

    if text in ["شروع", "/start"]:
        send_message(chat_id, "سلام 👋 یک گزینه رو انتخاب کن:", reply_markup=main_menu())
    elif text == "🔎 چند روز تا کنکور؟":
        send_message(chat_id, "یک کنکور رو انتخاب کن:", reply_markup=exam_menu())
    elif text in ["🧪 کنکور تجربی", "📐 کنکور ریاضی", "📚 کنکور انسانی", "🎨 کنکور هنر", "🏫 کنکور فرهنگیان"]:
        exam = text.replace("کنکور ", "").strip()
        send_message(chat_id, get_countdown(exam))
    elif text == "⏰ تنظیم یادآوری":
        waiting_exam[chat_id] = True
        send_message(chat_id, "📚 لطفاً یک کنکور رو انتخاب کن:", reply_markup=exam_menu())
    elif text == "❌ حذف یادآوری":
        delete_reminder(chat_id)
        send_message(chat_id, "✅ یادآوری شما حذف شد.", reply_markup=main_menu())
    elif text == "⬅️ بازگشت":
        send_message(chat_id, "↩️ بازگشتی به منوی اصلی:", reply_markup=main_menu())
    else:
        send_message(chat_id, "❌ دستور نامعتبر است. لطفاً از منو استفاده کنید.", reply_markup=main_menu())

# وب‌هوک
@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        if not data:
            return "ok"

        if "message" in data and "text" in data["message"]:
            chat_id = data["message"]["chat"]["id"]
            user_id = data["message"]["from"]["id"]
            text = data["message"]["text"]
            handle_message(chat_id, user_id, text)
    except Exception as e:
        logger.error(f"webhook error: {e}")
    return "ok"

# scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(send_reminders, 'interval', minutes=1)
scheduler.start()

# ست وبهوک
@app.route("/set_webhook")
def set_webhook():
    url = os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return "❌ PUBLIC_URL or RENDER_EXTERNAL_URL not set"
    wh_url = f"{url}/webhook/{TOKEN}"
    try:
        resp = requests.get(f"{TELEGRAM_API}/setWebhook?url={wh_url}")
        return resp.text
    except Exception as e:
        return f"❌ Error setting webhook: {e}"

if __name__ == "__main__":
    try:
        logger.info("🤖 Bot started successfully!")
        logger.info(f"🕒 Current Iran time: {get_iran_time()}")
        scheduler.start()
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
    finally:
        scheduler.shutdown()
