import os
import logging
from flask import Flask, request
import requests
import jdatetime
from datetime import datetime

# ------------------ تنظیمات ------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
PUBLIC_URL = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", BOT_TOKEN)

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ------------------ زمان کنکور ------------------
EXAMS = {
    "تجربی": jdatetime.datetime(1405, 4, 12, 8, 0, 0).togregorian(),
    "انسانی": jdatetime.datetime(1405, 4, 11, 8, 0, 0).togregorian(),
    "ریاضی": jdatetime.datetime(1405, 4, 11, 8, 0, 0).togregorian(),
    "هنر": jdatetime.datetime(1405, 4, 12, 14, 30, 0).togregorian(),
}

ALIASES = {
    "ریاضی": ["ریاضی", "mathematics", "math"],
    "تجربی": ["تجربی", "experimental", "science"],
    "انسانی": ["انسانی", "humanities", "human"],
    "هنر": ["هنر", "art"],
}

# ------------------ ابزارها ------------------
def time_until_exam(exam_datetime):
    now = datetime.now().replace(tzinfo=None)
    exam_dt = exam_datetime.replace(tzinfo=None)
    delta = exam_dt - now
    return delta

def format_timedelta(delta):
    days = delta.days
    seconds = delta.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{days} روز، {hours} ساعت و {minutes} دقیقه"

def get_exam_name(user_input):
    for exam, keywords in ALIASES.items():
        if user_input.lower() in [k.lower() for k in keywords]:
            return exam
    return None

def send_message(chat_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if keyboard:
        payload["reply_markup"] = {"keyboard": keyboard, "resize_keyboard": True}
    requests.post(f"{API_URL}/sendMessage", json=payload)

# ------------------ هندل آپدیت ------------------
def handle_update(update):
    if "message" not in update:
        return
    message = update["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    if text == "/start":
        keyboard = [[{"text": "ریاضی"}, {"text": "تجربی"}],
                    [{"text": "انسانی"}, {"text": "هنر"}]]
        send_message(chat_id, "سلام! رشته خودتو انتخاب کن:", keyboard)
        return

    exam = get_exam_name(text)
    if exam:
        delta = time_until_exam(EXAMS[exam])
        send_message(chat_id, f"تا کنکور {exam} {format_timedelta(delta)} مونده ⏳")
    else:
        send_message(chat_id, "لطفا یکی از رشته‌ها رو انتخاب کن یا /start رو بزن 🙂")

# ------------------ Flask ------------------
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    update = request.get_json()
    try:
        handle_update(update)
    except Exception as e:
        logging.exception("خطا در پردازش آپدیت")
    return "ok"

@app.route("/set_webhook")
def set_webhook():
    url = f"{PUBLIC_URL}/webhook/{WEBHOOK_SECRET}"
    r = requests.get(f"{API_URL}/setWebhook?url={url}")
    return r.json()

@app.route("/")
def index():
    return "ربات شمارش معکوس کنکور فعال است 🎯"

# ------------------ اجرا ------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
