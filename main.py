import os
import random
import logging
from flask import Flask, request
import requests
import jdatetime
import sqlite3
from datetime import datetime, timezone, timedelta

# ----------------- تنظیمات -----------------
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN در متغیرهای محیطی تنظیم نشده!")

BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
PUBLIC_URL = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", TOKEN)
WEBHOOK_URL = f"{PUBLIC_URL}/webhook/{WEBHOOK_SECRET}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------- دیتابیس -----------------
DB_FILE = "study.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS study_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            subject TEXT,
            start_time TEXT,
            duration REAL,
            date TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_study(user_id, subject, start_time, duration):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT INTO study_log (user_id, subject, start_time, duration, date) VALUES (?, ?, ?, ?, ?)",
                (user_id, subject, start_time, duration, datetime.utcnow().date().isoformat()))
    conn.commit()
    conn.close()

def get_study_summary(user_id, days=1):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    start_date = (datetime.utcnow().date() - timedelta(days=days-1)).isoformat()
    cur.execute("SELECT SUM(duration) FROM study_log WHERE user_id=? AND date >= ?", (user_id, start_date))
    result = cur.fetchone()[0]
    conn.close()
    return result or 0

def get_weekly_comparison(user_id):
    today = datetime.utcnow().date()
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("SELECT SUM(duration) FROM study_log WHERE user_id=? AND date BETWEEN ? AND ?",
                (user_id, (today - timedelta(days=6)).isoformat(), today.isoformat()))
    this_week = cur.fetchone()[0] or 0

    cur.execute("SELECT SUM(duration) FROM study_log WHERE user_id=? AND date BETWEEN ? AND ?",
                (user_id, (today - timedelta(days=13)).isoformat(), (today - timedelta(days=7)).isoformat()))
    last_week = cur.fetchone()[0] or 0

    conn.close()
    return this_week, last_week

# ----------------- جملات انگیزشی -----------------
QUOTES = [
    "✨ هر قدمی که برمی‌داری، تو رو به هدفت نزدیک‌تر می‌کنه!",
    "🚀 موفقیت از آن کسانی‌ست که ادامه می‌دهند.",
    "🔥 سختی‌ها می‌گذره، اما ثمره تلاش موندگار میشه.",
    "🌱 هر روز یه فرصت جدیده برای بهتر شدن.",
    "🏆 باور داشته باش، تو می‌تونی!",
    "💡 کنکور فقط یک مرحله‌ست، آینده تو خیلی روشن‌تره!"
]

def get_random_quote():
    return random.choice(QUOTES)

# ----------------- ربات -----------------
def send_message(chat_id: int, text: str, reply_markup=None):
    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
    r = requests.post(url, json=payload)
    if not r.ok:
        logger.error(f"❌ ارسال پیام ناموفق: {r.text}")

def build_keyboard():
    return {
        "keyboard": [
            [{"text": "📊 گزارش مطالعه"}],
            [{"text": "🏠 بازگشت به منو"}],
        ],
        "resize_keyboard": True
    }

# ----------------- Flask -----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "ربات شمارش معکوس + مدیریت مطالعه فعال است ✅"

@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    data = request.get_json()
    logger.info(f"آپدیت: {data}")

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        if text.startswith("/add"):
            try:
                _, subject, start, duration = text.split(maxsplit=3)
                add_study(chat_id, subject, start, float(duration))
                send_message(chat_id, f"✅ مطالعه {subject} به مدت {duration} ساعت ثبت شد.", build_keyboard())
            except Exception as e:
                send_message(chat_id, "❌ فرمت درست: /add <درس> <ساعت شروع> <مدت ساعت>", build_keyboard())

        elif text.startswith("/today"):
            total = get_study_summary(chat_id, 1)
            send_message(chat_id, f"📚 امروز {total:.1f} ساعت درس خوندی.", build_keyboard())

        elif text.startswith("/week") or text == "📊 گزارش مطالعه":
            this_week, last_week = get_weekly_comparison(chat_id)
            diff = this_week - last_week
            trend = "📈 پیشرفت" if diff > 0 else ("📉 پسرفت" if diff < 0 else "➡️ بدون تغییر")
            send_message(chat_id,
                         f"📊 گزارش مطالعه هفتگی:\n"
                         f"این هفته: {this_week:.1f} ساعت\n"
                         f"هفته قبل: {last_week:.1f} ساعت\n"
                         f"{trend}: {diff:.1f} ساعت",
                         build_keyboard())

        elif text in ["/start", "start", "🏠 بازگشت به منو"]:
            send_message(chat_id, "👋 خوش اومدی!\nاز دستورات زیر استفاده کن:\n"
                                  "/add <درس> <ساعت شروع> <مدت ساعت>\n"
                                  "/today → مجموع امروز\n"
                                  "/week → گزارش هفتگی", build_keyboard())

    return {"ok": True}

# ----------------- ست وبهوک -----------------
def set_webhook():
    url = f"{BASE_URL}/setWebhook"
    r = requests.post(url, json={"url": WEBHOOK_URL})
    logger.info(f"تنظیم وبهوک: {r.text}")

if __name__ == "__main__":
    init_db()
    set_webhook()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
