import os
import logging
from flask import Flask, request, jsonify
import requests
import jdatetime
from dotenv import load_dotenv

# ---------------------------
# تنظیمات لاگ
# ---------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ---------------------------
# بارگذاری متغیرها
# ---------------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", BOT_TOKEN)
PUBLIC_URL = os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN در محیط تنظیم نشده!")

# ---------------------------
# داده‌های کنکور
# ---------------------------
EXAMS = {
    "تجربی": jdatetime.date(1405, 4, 12),
    "هنر": jdatetime.date(1405, 4, 12),
    "ریاضی": jdatetime.date(1405, 4, 11),
    "انسانی": jdatetime.date(1405, 4, 11),
}

# ---------------------------
# اپ Flask
# ---------------------------
app = Flask(__name__)
app.logger.setLevel(logging.DEBUG)

@app.errorhandler(Exception)
def handle_error(e):
    logger.exception("❌ Unhandled Exception")
    return jsonify({"ok": False, "error": str(e)}), 500

# ---------------------------
# توابع ربات
# ---------------------------
def send_message(chat_id: int, text: str, with_keyboard: bool = False) -> None:
    """ارسال پیام به کاربر"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    if with_keyboard:
        payload["reply_markup"] = {
            "keyboard": [[{"text": k}] for k in EXAMS.keys()],
            "resize_keyboard": True,
            "one_time_keyboard": False,
        }

    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        logger.info(f"📤 پیام به {chat_id} ارسال شد: {text}")
    except Exception as e:
        logger.error(f"❌ خطا در ارسال پیام به {chat_id}: {e}")

def get_countdown_message(exam_name: str) -> str:
    today = jdatetime.date.today()
    exam_date = EXAMS.get(exam_name)
    if not exam_date:
        return "❓ رشته نامعتبر است."

    delta = exam_date - today
    if delta.days < 0:
        return f"✅ آزمون {exam_name} در تاریخ {exam_date} برگزار شده است!"
    else:
        return f"⏳ تا آزمون {exam_name} در تاریخ {exam_date}، {delta.days} روز باقی مانده است."

def resolve_exam_name(text: str) -> str | None:
    text = text.strip()
    for key in EXAMS.keys():
        if key in text:
            return key
    return None

def handle_message(chat_id: int, text: str) -> None:
    logger.info(f"📩 پیام از {chat_id}: {repr(text)}")

    if text.startswith("/start") or "منو" in text:
        send_message(chat_id, "سلام! یکی از گزینه‌های زیر رو انتخاب کن:", with_keyboard=True)
        return

    exam_key = resolve_exam_name(text)
    logger.info(f"🔍 نتیجه resolve_exam_name: {exam_key}")

    if exam_key:
        response = get_countdown_message(exam_key)
        logger.info(f"✅ پاسخ تولید شد: {response}")
        send_message(chat_id, response)
    else:
        logger.warning(f"⚠️ رشته ناشناخته: {text}")
        send_message(chat_id, "❓ رشته شناخته نشد. لطفاً یکی از گزینه‌های منو رو انتخاب کنید.", with_keyboard=True)

# ---------------------------
# مسیرهای Flask
# ---------------------------
@app.route("/", methods=["GET"])
def index():
    return "ربات شمارش معکوس کنکور فعال است ✅"

@app.route(f"/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        logger.info(f"📥 آپدیت از تلگرام: {data}")

        if "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            handle_message(chat_id, text)

    except Exception as e:
        logger.exception("❌ خطا در پردازش آپدیت تلگرام")
        return jsonify({"ok": False}), 500

    return jsonify({"ok": True})

# ---------------------------
# تنظیم وبهوک
# ---------------------------
@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    if not PUBLIC_URL:
        return "❌ PUBLIC_URL یا RENDER_EXTERNAL_URL تنظیم نشده", 500

    url = f"{PUBLIC_URL}/webhook/{WEBHOOK_SECRET}"
    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    r = requests.post(api_url, json={"url": url})

    if r.status_code == 200:
        return f"✅ وبهوک تنظیم شد: {url}"
    else:
        return f"❌ خطا در تنظیم وبهوک: {r.text}", 500

# ---------------------------
# اجرای لوکال
# ---------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
