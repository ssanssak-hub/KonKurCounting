import os
import json
import time
import logging
import jdatetime
import requests
import pickle
import atexit
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
user_reminders = {}  # {chat_id: {"enabled": True/False, "time": "08:00", "exams": []}}

# پشتیبان‌گیری
BACKUP_FILE = "user_data_backup.pkl"

def load_backup():
    """بارگذاری داده‌های ذخیره شده"""
    global user_study, user_reminders
    try:
        with open(BACKUP_FILE, 'rb') as f:
            data = pickle.load(f)
            user_study = data.get('user_study', {})
            user_reminders = data.get('user_reminders', {})
        logger.info("✅ Backup loaded successfully")
    except FileNotFoundError:
        logger.info("ℹ️ No backup file found, starting fresh")
        user_study = {}
        user_reminders = {}

def save_backup():
    """ذخیره داده‌ها"""
    try:
        data = {
            'user_study': user_study,
            'user_reminders': user_reminders
        }
        with open(BACKUP_FILE, 'wb') as f:
            pickle.dump(data, f)
        logger.info("✅ Backup saved successfully")
    except Exception as e:
        logger.error(f"Backup save error: {e}")

# بارگذاری اولیه
load_backup()
atexit.register(save_backup)

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
            [{"text": "🔔 بهم یادآوری کن!"}],
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

# کیبورد مدیریت یادآوری
def reminder_menu():
    return {
        "keyboard": [
            [{"text": "✅ فعال کردن یادآوری"}, {"text": "❌ غیرفعال کردن یادآوری"}],
            [{"text": "🕐 تنظیم زمان یادآوری"}, {"text": "📝 انتخاب کنکورها"}],
            [{"text": "📋 مشاهده تنظیمات"}],
            [{"text": "⬅️ بازگشت"}],
        ],
        "resize_keyboard": True,
    }

# کیبورد انتخاب کنکور برای یادآوری
def reminder_exam_menu():
    return {
        "keyboard": [
            [{"text": "🧪 تجربی"}, {"text": "📐 ریاضی"}],
            [{"text": "📚 انسانی"}, {"text": "🎨 هنر"}],
            [{"text": "🏫 فرهنگیان"}],
            [{"text": "✅ تایید انتخاب"}],
            [{"text": "⬅️ بازگشت"}],
        ],
        "resize_keyboard": True,
    }

# ارسال یادآوری به کاربر
def send_reminder_to_user(chat_id: int):
    """ارسال یادآوری کنکور به کاربر خاص"""
    if chat_id not in user_reminders or not user_reminders[chat_id].get("enabled", False):
        return
    
    user_exams = user_reminders[chat_id].get("exams", [])
    if not user_exams:
        return
    
    reminder_text = "⏰ یادآوری روزانه کنکور:\n\n"
    for exam_name in user_exams:
        if exam_name in EXAMS:
            reminder_text += get_countdown(exam_name) + "\n\n"
    
    send_message(chat_id, reminder_text)

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
                f"📅 تاریخ: {exam['date'].strftime('%d %B %Y')}\n"
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

    elif text == "🔔 بهم یادآوری کن!":
        send_message(chat_id, "🔔 مدیریت یادآوری روزانه:", reply_markup=reminder_menu())

    elif text == "✅ فعال کردن یادآوری":
        if chat_id not in user_reminders:
            user_reminders[chat_id] = {"enabled": True, "time": "08:00", "exams": []}
        else:
            user_reminders[chat_id]["enabled"] = True
        send_message(chat_id, "✅ یادآوری روزانه فعال شد", reply_markup=reminder_menu())
        save_backup()

    elif text == "❌ غیرفعال کردن یادآوری":
        if chat_id in user_reminders:
            user_reminders[chat_id]["enabled"] = False
        send_message(chat_id, "❌ یادآوری روزانه غیرفعال شد", reply_markup=reminder_menu())
        save_backup()

    elif text == "🕐 تنظیم زمان یادآوری":
        send_message(chat_id, "⏰ لطفاً زمان یادآوری را به فرمت HH:MM وارد کنید (مثلاً 08:00):", reply_markup=reminder_menu())

    elif text == "📝 انتخاب کنکورها":
        send_message(chat_id, "📝 کنکورهای مورد نظر برای یادآوری را انتخاب کنید:", reply_markup=reminder_exam_menu())

    elif text == "📋 مشاهده تنظیمات":
        if chat_id in user_reminders and user_reminders[chat_id].get("enabled", False):
            settings = user_reminders[chat_id]
            exams_text = ", ".join(settings.get("exams", [])) or "هیچکدام"
            text_msg = f"🔧 تنظیمات یادآوری:\n\n⏰ زمان: {settings.get('time', '08:00')}\n📚 کنکورها: {exams_text}\n✅ وضعیت: فعال"
        else:
            text_msg = "🔕 یادآوری غیرفعال است"
        send_message(chat_id, text_msg, reply_markup=reminder_menu())

    elif text == "✅ تایید انتخاب":
        send_message(chat_id, "✅ کنکورهای مورد نظر برای یادآوری ثبت شدند", reply_markup=reminder_menu())
        save_backup()

    elif text in ["🧪 تجربی", "📐 ریاضی", "📚 انسانی", "🎨 هنر", "🏫 فرهنگیان"] and "user_reminder_state" in globals():
        # مدیریت انتخاب کنکورها برای یادآوری
        exam_name = text.split(" ")[1] if " " in text else text
        if chat_id not in user_reminders:
            user_reminders[chat_id] = {"enabled": True, "time": "08:00", "exams": []}
        
        if exam_name in user_reminders[chat_id].get("exams", []):
            user_reminders[chat_id]["exams"].remove(exam_name)
            send_message(chat_id, f"❌ {exam_name} از لیست یادآوری حذف شد", reply_markup=reminder_exam_menu())
        else:
            if "exams" not in user_reminders[chat_id]:
                user_reminders[chat_id]["exams"] = []
            user_reminders[chat_id]["exams"].append(exam_name)
            send_message(chat_id, f"✅ {exam_name} به لیست یادآوری اضافه شد", reply_markup=reminder_exam_menu())
        save_backup()

    elif text == "➕ ثبت مطالعه":
        send_message(
            chat_id,
            "📚 لطفاً اطلاعات مطالعه را به این شکل وارد کنید:\n\n"
            "نام درس، ساعت شروع (hh:mm)، ساعت پایان (hh:mm)، مدت (ساعت)\n\n"
            "مثال:\nریاضی، 14:00، 16:00، 2",
            reply_markup=study_menu()
        )

    elif text == "📊 مشاهده پیشرفت":
        logs = user_study.get(chat_id, [])
        if not logs:
            send_message(chat_id, "📭 هنوز مطالعه‌ای ثبت نکردی.", reply_markup=study_menu())
        else:
            total = sum(entry["duration"] for entry in logs)
            details = "\n".join(
                f"• {e['subject']} | {e['start']} تا {e['end']} | {e['duration']} ساعت"
                for e in logs
            )
            send_message(chat_id, f"📊 مجموع مطالعه: {total} ساعت\n\n{details}", reply_markup=study_menu())

    elif text == "🗑️ حذف مطالعه":
        logs = user_study.get(chat_id, [])
        if not logs:
            send_message(chat_id, "📭 چیزی برای حذف وجود نداره.", reply_markup=study_menu())
        else:
            for idx, e in enumerate(logs):
                msg = f"• {e['subject']} | {e['start']} تا {e['end']} | {e['duration']} ساعت"
                inline_kb = [[{"text": "❌ حذف", "callback_data": f"delete_{idx}"}]]
                send_message_inline(chat_id, msg, inline_kb)

    elif text == "⬅️ بازگشت":
        send_message(chat_id, "↩️ بازگشتی به منوی اصلی:", reply_markup=main_menu())

    elif text.count(":") == 1 and len(text) == 5 and text.replace(":", "").isdigit():
        # مدیریت زمان یادآوری
        if chat_id not in user_reminders:
            user_reminders[chat_id] = {"enabled": True, "time": text, "exams": []}
        else:
            user_reminders[chat_id]["time"] = text
        
        send_message(chat_id, f"✅ زمان یادآوری روی {text} تنظیم شد", reply_markup=reminder_menu())
        save_backup()

    elif text.startswith("🧪") and "کنکور" in text:
        send_message(chat_id, get_countdown("تجربی"))
    elif text.startswith("📐") and "کنکور" in text:
        send_message(chat_id, get_countdown("ریاضی"))
    elif text.startswith("📚") and "کنکور" in text:
        send_message(chat_id, get_countdown("انسانی"))
    elif text.startswith("🎨") and "کنکور" in text:
        send_message(chat_id, get_countdown("هنر"))
    elif text.startswith("🏫") and "کنکور" in text:
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
                send_message(chat_id, f"✅ مطالعه {subject} از {start_time} تا {end_time} به مدت {duration} ساعت ثبت شد.", reply_markup=study_menu())
                save_backup()
            else:
                send_message(chat_id, "❌ فرمت اشتباه است. لطفاً دوباره وارد کن.", reply_markup=study_menu())
        except Exception as e:
            logger.error(f"Study parse error: {e}")
            send_message(chat_id, "⚠️ مشکلی در ثبت پیش آمد. دوباره امتحان کن.", reply_markup=study_menu())

# هندل callback queries
def handle_callback_query(chat_id: int, callback_data: str, callback_id: str):
    if callback_data.startswith("delete_"):
        idx = int(callback_data.split("_")[1])
        if chat_id in user_study and 0 <= idx < len(user_study[chat_id]):
            removed = user_study[chat_id].pop(idx)
            send_message(chat_id, f"🗑️ مطالعه {removed['subject']} حذف شد.", reply_markup=study_menu())
            save_backup()
        answer_callback_query(callback_id, "حذف شد ✅")

# وب‌هوک
@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"📩 Update: {data}")

        if "callback_query" in data:
            cq = data["callback_query"]
            chat_id = cq["message"]["chat"]["id"]
            cq_data = cq["data"]
            handle_callback_query(chat_id, cq_data, cq["id"])

        elif "message" in data:
            chat_id = data["message"]["chat"]["id"]
            text = data["message"].get("text", "")
            handle_message(chat_id, text)
            
    except Exception as e:
        logger.error(f"webhook error: {e}")
    return "ok"

# تابع ارسال یادآوری روزانه
def send_daily_reminders():
    """ارسال یادآوری روزانه به همه کاربران"""
    try:
        now = jdatetime.datetime.now().strftime("%H:%M")
        logger.info(f"🔔 Checking reminders at {now}")
        
        for chat_id, settings in user_reminders.items():
            if settings.get("enabled", False) and settings.get("time", "") == now and settings.get("exams"):
                logger.info(f"Sending reminder to {chat_id}")
                send_reminder_to_user(chat_id)
                
    except Exception as e:
        logger.error(f"Reminder error: {e}")

# scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(send_daily_reminders, 'interval', minutes=1)
scheduler.start()

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
    try:
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
    finally:
        scheduler.shutdown()
        save_backup()
