import os
import json
import time
import logging
import jdatetime
import requests
from datetime import datetime, timezone
from flask import Flask, request
from dotenv import load_dotenv

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

# ارسال پیام
def send_message(chat_id: int, text: str, reply_markup: dict | None = None):
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
        ],
        "resize_keyboard": True,
    }

# کیبورد انتخاب کنکور
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

# هندل پیام‌ها
def handle_message(chat_id: int, text: str):
    if text in ["شروع", "/start"]:
        send_message(chat_id, "سلام 👋 یک گزینه رو انتخاب کن:", reply_markup=main_menu())

    elif text == "🔎 چند روز تا کنکور؟":
        send_message(chat_id, "یک کنکور رو انتخاب کن:", reply_markup=exam_menu())

    elif text == "📖 برنامه‌ریزی":
        send_message(chat_id, "📖 بخش برنامه‌ریزی:", reply_markup=study_menu())

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

    elif text.startswith("🧪"):
        send_message(chat_id, get_countdown("تجربی"))
    elif text.startswith("📐"):
        send_message(chat_id, get_countdown("ریاضی"))
    elif text.startswith("📚"):
        send_message(chat_id, get_countdown("انسانی"))
    elif text.startswith("🎨"):
        send_message(chat_id, get_countdown("هنر"))
    elif text.startswith("🏫"):
        send_message(chat_id, get_countdown("فرهنگیان"))

    else:
        # تلاش برای ثبت مطالعه
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
            else:
                send_message(chat_id, "❌ فرمت اشتباه است. لطفاً دوباره وارد کن.")
        except Exception as e:
            logger.error(f"Study parse error: {e}")
            send_message(chat_id, "⚠️ مشکلی در ثبت پیش آمد. دوباره امتحان کن.")

# هندل دکمه حذف
@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"📩 Update: {data}")

        if "callback_query" in data:
            cq = data["callback_query"]
            chat_id = cq["message"]["chat"]["id"]
            cq_data = cq["data"]
            if cq_data.startswith("delete_"):
                idx = int(cq_data.split("_")[1])
                if chat_id in user_study and 0 <= idx < len(user_study[chat_id]):
                    removed = user_study[chat_id].pop(idx)
                    send_message(chat_id, f"🗑️ مطالعه {removed['subject']} حذف شد.")
                answer_callback_query(cq["id"], "حذف شد ✅")

        elif "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            handle_message(chat_id, text)
    except Exception as e:
        logger.error(f"webhook error: {e}")
    return "ok"

# ست وبهوک
@app.route("/set_webhook")
def set_webhook():
    url = os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return "❌ PUBLIC_URL or RENDER_EXTERNAL_URL not set"
    wh_url = f"{url}/webhook/{TOKEN}"
    resp = requests.get(f"{TELEGRAM_API}/setWebhook?url={wh_url}")
    return resp.text

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
