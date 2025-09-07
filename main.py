import os
import logging
from flask import Flask, request
import requests
import jdatetime
from datetime import datetime

# -------------------
# تنظیم لاگر
# -------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------
# کانفیگ
# -------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
PUBLIC_URL = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("PUBLIC_URL")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET") or BOT_TOKEN
WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}"

app = Flask(__name__)

# تاریخ‌های کنکور
EXAM_DATES = {
    "تجربی": jdatetime.date(1405, 4, 12),
    "هنر": jdatetime.date(1405, 4, 12),
    "ریاضی": jdatetime.date(1405, 4, 11),
    "انسانی": jdatetime.date(1405, 4, 11),
}

# -------------------
# توابع اصلی
# -------------------
def send_message(chat_id: int, text: str) -> None:
    """ارسال پیام به کاربر"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        resp = requests.post(url, json=payload)
        logger.info(f"📤 پیام ارسال شد به {chat_id}: {text} | status={resp.status_code}")
    except Exception as e:
        logger.error(f"❌ خطا در ارسال پیام: {e}")

def get_countdown_message(exam_key: str) -> str:
    """محاسبه روزهای باقی مانده"""
    today = jdatetime.date.today()
    target_date = EXAM_DATES[exam_key]
    delta = (target_date.togregorian() - today.togregorian()).days
    if delta > 0:
        return f"تا کنکور {exam_key} {delta} روز باقی مانده ⏳"
    elif delta == 0:
        return f"امروز روز برگزاری کنکور {exam_key} است! 🎉"
    else:
        return f"کنکور {exam_key} برگزار شده است."

def resolve_exam_name(text: str):
    for key in EXAM_DATES:
        if key in text:
            return key
    return None

def handle_message(chat_id: int, text: str) -> None:
    logger.info(f"📩 پیام از {chat_id}: {text}")
    exam_key = resolve_exam_name(text)
    if exam_key:
        response = get_countdown_message(exam_key)
        logger.info(f"✅ شناخته شد: {exam_key} → {response}")
        send_message(chat_id, response)
    else:
        logger.warning(f"⚠️ ناشناخته: {text}")
        send_message(chat_id, "لطفاً یکی از گزینه‌های منو رو انتخاب کن 🙂")

# -------------------
# وبهوک
# -------------------
@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook() -> str:
    update = request.get_json(force=True, silent=True)
    logger.info(f"🔔 آپدیت دریافتی: {update}")

    if not update:
        return "no update"

    if "message" in update and "text" in update["message"]:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"]["text"]
        handle_message(chat_id, text)

    return "ok"

# -------------------
# ست وبهوک
# -------------------
@app.route("/set_webhook", methods=["GET"])
def set_webhook() -> str:
    if not PUBLIC_URL:
        return "❌ PUBLIC_URL یا RENDER_EXTERNAL_URL تنظیم نشده."

    webhook_url = f"{PUBLIC_URL}{WEBHOOK_PATH}"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    resp = requests.post(url, json={"url": webhook_url})
    logger.info(f"🌍 درخواست ست وبهوک → {webhook_url} | status={resp.status_code}")
    return resp.text

# -------------------
# اجرای لوکال
# -------------------
if __name__ == "__main__":
    app.run(port=5000, debug=True)
