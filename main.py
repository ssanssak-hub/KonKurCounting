import os
import random
import logging
from flask import Flask, request
import requests
import jdatetime
from datetime import datetime, timezone

# ----------------- تنظیمات -----------------
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN در متغیرهای محیطی تنظیم نشده!")

BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

# استفاده از لینک رندر
PUBLIC_URL = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_URL")
if not PUBLIC_URL:
    raise ValueError("❌ PUBLIC_URL یا RENDER_EXTERNAL_URL تعریف نشده!")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", TOKEN)
WEBHOOK_URL = f"{PUBLIC_URL}/webhook/{WEBHOOK_SECRET}"

# ----------------- لاگ -----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------- لیست آزمون‌ها -----------------
EXAMS = {
    "تجربی": (jdatetime.datetime(1405, 4, 12, 8, 0), "🧪"),
    "ریاضی": (jdatetime.datetime(1405, 4, 11, 8, 0), "📐"),
    "انسانی": (jdatetime.datetime(1405, 4, 11, 8, 0), "📚"),
    "هنر": (jdatetime.datetime(1405, 4, 12, 14, 30), "🎨"),
    "فرهنگیان - روز اول": (jdatetime.datetime(1405, 2, 17, 8, 0), "🏫"),
    "فرهنگیان - روز دوم": (jdatetime.datetime(1405, 2, 18, 8, 0), "🏫"),
}

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

# ----------------- توابع ربات -----------------
def build_keyboard() -> dict:
    keyboard = [
        [{"text": "🧪 تجربی"}, {"text": "📐 ریاضی"}],
        [{"text": "📚 انسانی"}, {"text": "🎨 هنر"}],
        [{"text": "🏫 فرهنگیان - روز اول"}, {"text": "🏫 فرهنگیان - روز دوم"}],
        [{"text": "🏠 بازگشت به منو"}],
    ]
    return {"keyboard": keyboard, "resize_keyboard": True}

def countdown_text(exam: str, exam_date: jdatetime.datetime, emoji: str) -> str:
    now = datetime.now(timezone.utc)
    exam_dt = exam_date.togregorian().replace(tzinfo=timezone.utc)
    delta = exam_dt - now

    if delta.total_seconds() <= 0:
        return f"{emoji} کنکور «{exam}» برگزار شده است! ✅"

    days, remainder = divmod(int(delta.total_seconds()), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    date_str = exam_date.strftime("%A %d %B %Y - %H:%M")
    quote = get_random_quote()

    return (
        f"{emoji} شمارش معکوس کنکور «{exam}»\n"
        f"⏳ {days} روز، {hours} ساعت و {minutes} دقیقه مونده!\n"
        f"🗓 تاریخ برگزاری: {date_str}\n\n"
        f"💡 جمله انگیزشی: {quote}"
    )

def send_message(chat_id: int, text: str, reply_markup=None):
    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": reply_markup,
    }
    r = requests.post(url, json=payload)
    if not r.ok:
        logger.error(f"ارسال پیام ناموفق بود: {r.text}")

# ----------------- Flask -----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "ربات شمارش معکوس کنکور فعال است ✅"

@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"آپدیت جدید: {data}")

        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")

            if text in ["start", "/start", "🏠 بازگشت به منو"]:
                send_message(chat_id, "📋 یکی از آزمون‌ها رو انتخاب کن:", build_keyboard())
            else:
                exam_name = text.replace("🧪 ", "").replace("📐 ", "").replace("📚 ", "").replace("🎨 ", "").replace("🏫 ", "")
                if exam_name in EXAMS:
                    exam_date, emoji = EXAMS[exam_name]
                    msg = countdown_text(exam_name, exam_date, emoji)
                    send_message(chat_id, msg, build_keyboard())
                else:
                    send_message(chat_id, "❌ آزمون نامعتبر. لطفاً از منو انتخاب کنید.", build_keyboard())

        return {"ok": True}
    except Exception as e:
        logger.error(f"❌ خطا در پردازش وبهوک: {e}", exc_info=True)
        return {"ok": False}, 500

# ----------------- ست وبهوک -----------------
def set_webhook():
    url = f"{BASE_URL}/setWebhook"
    payload = {"url": WEBHOOK_URL}
    r = requests.post(url, json=payload)
    logger.info(f"تنظیم وبهوک: {r.text}")

if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
