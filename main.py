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
TOKEN = os.getenv("BOT_TOKEN", "توکن_بات_اینجا")
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

# ================== زمان‌بندی گزارش روزانه ==================
def schedule_daily_report(chat_id: int, time_str: str, exams: List[str]) -> List[str]:
    h, m = map(int, time_str.split(":"))
    job_ids = []
    for ex in exams:
        job_id = f"report|{chat_id}|{time_str}|{ex}"

        def _send(chat_id=chat_id, exam=ex):
            msg = f"📅 گزارش روزانه\n{get_countdown(exam)}"
            send_message(chat_id, msg)

        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)

        scheduler.add_job(_send, CronTrigger(hour=h, minute=m, timezone=TEHRAN_TZ), id=job_id)
        job_ids.append(job_id)

    user_reminders.setdefault(chat_id, {}).setdefault("user_reports", []).append(
        {"time": time_str, "exams": exams, "job_ids": job_ids}
    )
    return job_ids

# ================== هندل پیام‌ها ==================
def handle_message(chat_id: int, text: str):
    if chat_id in user_reminders and user_reminders[chat_id].get("step") == "set_time":
        if text == "⬅️ بازگشت":
            user_reminders[chat_id]["step"] = None
            user_reminders[chat_id]["pending_exam"] = None
            send_message(chat_id, "↩️ بازگشتی به منوی اصلی:", reply_markup=main_menu())
            return
        try:
            reminder_time = normalize_time_str(text)
            exam_name = user_reminders[chat_id]["pending_exam"]
            schedule_reminder(chat_id, exam_name, reminder_time)
            user_reminders[chat_id]["step"] = None
            user_reminders[chat_id]["pending_exam"] = None
            send_message(chat_id, f"✅ یادآوری برای کنکور {exam_name} هر روز در ساعت {reminder_time} تنظیم شد.")
        except Exception:
            logger.error(f"reminder error: {traceback.format_exc()}")
            send_message(chat_id, "⚠️ فرمت ساعت درست نیست. لطفاً به صورت 24 ساعته وارد کن (مثال‌ها: 20:00، 07:30).")
        return

    if text in ["شروع", "/start"]:
        send_message(chat_id, "سلام 👋 یک گزینه رو انتخاب کن:", reply_markup=main_menu())
        return

    elif text == "🔎 چند روز تا کنکور؟":
        send_message(chat_id, "یک کنکور رو انتخاب کن:", reply_markup=exam_menu())
        return

    elif text == "📖 برنامه‌ریزی":
        send_message(chat_id, "📖 بخش برنامه‌ریزی:", reply_markup=study_menu())
        return

    elif text == "🔔 بهم یادآوری کن!":
        send_message(chat_id, "برای کدوم کنکور می‌خوای یادآوری تنظیم کنی یا مدیریت کنی؟", reply_markup=exam_menu(include_reminder_manage=True))
        user_reminders.setdefault(chat_id, {"reminders": [], "step": None, "pending_exam": None})
        user_reminders[chat_id]["step"] = "choose_exam"
        user_reminders[chat_id]["pending_exam"] = None
        return

    elif text == "❌ مدیریت یادآوری‌ها":
        reminders = user_reminders.get(chat_id, {}).get("reminders", [])
        reports = user_reminders.get(chat_id, {}).get("user_reports", [])
        if not reminders and not reports:
            send_message(chat_id, "📭 هیچ یادآوری فعالی نداری.")
        else:
            for r in reminders:
                msg = f"🔔 کنکور {r['exam']} – ساعت {r['time']}"
                inline_kb = [[{"text": "❌ حذف", "callback_data": f"remdel|{r['exam']}"}]]
                send_message_inline(chat_id, msg, inline_kb)
            for idx, r in enumerate(reports):
                msg = f"📅 گزارش روزانه | ساعت: {r['time']} | کنکورها: {', '.join(r['exams'])}"
                inline_kb = [[{"text": "❌ حذف", "callback_data": f"reportrm|{idx}"}]]
                send_message_inline(chat_id, msg, inline_kb)
        return

    elif text == "📅 گزارش روزانه کنکورها":
        user_reminders.setdefault(chat_id, {"reminders": [], "step": None, "pending": {}, "user_reports": []})
        user_reminders[chat_id]["step"] = "report_choose_exams"
        user_reminders[chat_id]["pending"] = {"exams": []}
        send_message(chat_id, "🔎 کنکورهایی رو که می‌خوای توی گزارش روزانه باشن انتخاب کن:", reply_markup=exam_menu())
        return

    elif user_reminders.get(chat_id, {}).get("step") == "report_choose_exams":
        exam_name = text.split()[-1]
        user_reminders[chat_id]["pending"]["exams"].append(exam_name)
        user_reminders[chat_id]["step"] = "report_set_time"
        send_message(chat_id, "⏰ حالا ساعت(های) گزارش رو بده.\nچند ساعت هم می‌تونی بدی با کاما جدا کنی (مثال: 08:00, 20:00).")
        return

    elif user_reminders.get(chat_id, {}).get("step") == "report_set_time":
        try:
            times = parse_times_list(text)
            exams = user_reminders[chat_id]["pending"]["exams"]
            for t in times:
                schedule_daily_report(chat_id, t, exams)
            user_reminders[chat_id]["step"] = None
            user_reminders[chat_id]["pending"] = {}
            send_message(chat_id, f"✅ گزارش روزانه برای کنکورهای {', '.join(exams)} در ساعات {', '.join(times)} تنظیم شد.",
                         reply_markup=reminder_root_menu())
        except Exception:
            send_message(chat_id, "❌ فرمت ساعت‌ها اشتباهه. مثال درست: 08:00 یا 08:00, 20:00")
        return

    elif text in ["🧪 کنکور تجربی", "📐 کنکور ریاضی", "📚 کنکور انسانی", "🎨 کنکور هنر", "🏫 کنکور فرهنگیان"]:
        exam_name = text.split()[-1]
        if user_reminders.get(chat_id, {}).get("step") == "choose_exam":
            user_reminders[chat_id]["pending_exam"] = exam_name
            user_reminders[chat_id]["step"] = "set_time"
            send_message(chat_id,
                f"⏰ لطفاً ساعت یادآوری روزانه برای کنکور {exam_name} رو وارد کن.\n"
                f"فرمت باید 24 ساعته باشه (HH:MM). مثال: 20:00 یا 07:30"
            )
        else:
            countdown = get_countdown(exam_name)
            send_message(chat_id, countdown)
        return

    elif text == "➕ ثبت مطالعه":
        send_message(chat_id, "📚 لطفاً اطلاعات مطالعه را به این شکل وارد کنید:\nنام درس، ساعت شروع، ساعت پایان، مدت (ساعت)\nمثال:\nریاضی، 14:00، 16:00، 2")
        return

    elif text == "📊 مشاهده پیشرفت":
        logs = user_study.get(chat_id, [])
        if not logs:
            send_message(chat_id, "📭 هنوز مطالعه‌ای ثبت نکردی.")
        else:
            total = sum(entry["duration"] for entry in logs)
            details = "\n".join(f"• {e['subject']} | {e['start']} تا {e['end']} | {e['duration']} ساعت" for e in logs)
            send_message(chat_id, f"📊 مجموع مطالعه: {total} ساعت\n\n{details}")
        return

    elif text == "🗑️ حذف مطالعه":
        logs = user_study.get(chat_id, [])
        if not logs:
            send_message(chat_id, "📭 چیزی برای حذف وجود نداره.")
        else:
            for idx, e in enumerate(logs):
                msg = f"• {e['subject']} | {e['start']} تا {e['end']} | {e['duration']} ساعت"
                inline_kb = [[{"text": "❌ حذف", "callback_data": f"delete_{idx}"}]]
                send_message_inline(chat_id, msg, inline_kb)
        return

    elif text == "⬅️ بازگشت":
        send_message(chat_id, "↩️ بازگشتی به منوی اصلی:", reply_markup=main_menu())
        return

    else:
        try:
            parts = [p.strip() for p in text.split("،")]
            if len(parts) == 4:
                subject, start_time, end_time, duration = parts
                duration = float(duration)
                user_study.setdefault(chat_id, []).append({"subject": subject, "start": start_time, "end": end_time, "duration": duration})
                send_message(chat_id, f"✅ مطالعه {subject} از {start_time} تا {end_time} به مدت {duration} ساعت ثبت شد.")
            else:
                send_message(chat_id, "❌ فرمت اشتباه است. لطفاً دوباره وارد کن.")
        except Exception:
            logger.error(f"Study parse error: {traceback.format_exc()}")
            send_message(chat_id, "⚠️ مشکلی در ثبت پیش آمد. دوباره امتحان کن.")
        return

# ================== هندل کال‌بک ==================
def handle_callback(data, chat_id, message_id, callback_query_id):
    if data.startswith("delete_"):
        idx = int(data.split("_")[1])
        logs = user_study.get(chat_id, [])
        if 0 <= idx < len(logs):
            logs.pop(idx)
            send_answer_callback(callback_query_id, "🗑️ حذف شد")
    elif data.startswith("remdel|"):
        exam = data.split("|")[1]
        reminders = user_reminders.get(chat_id, {}).get("reminders", [])
        user_reminders[chat_id]["reminders"] = [r for r in reminders if r["exam"] != exam]
        send_answer_callback(callback_query_id, "❌ یادآوری حذف شد")
    elif data.startswith("reportrm|"):
        idx = int(data.split("|")[1])
        reports = user_reminders.get(chat_id, {}).get("user_reports", [])
        if 0 <= idx < len(reports):
            rep = reports.pop(idx)
            for jid in rep.get("job_ids", []):
                if scheduler.get_job(jid):
                    scheduler.remove_job(jid)
            send_answer_callback(callback_query_id, "📭 گزارش روزانه حذف شد")

# ================== وبهوک ==================
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    try:
        update = request.get_json()
        if "message" in update:
            chat_id = update["message"]["chat"]["id"]
            text = update["message"].get("text", "")
            handle_message(chat_id, text)
        elif "callback_query" in update:
            cq = update["callback_query"]
            data = cq["data"]
            chat_id = cq["message"]["chat"]["id"]
            message_id = cq["message"]["message_id"]
            callback_query_id = cq["id"]
            handle_callback(data, chat_id, message_id, callback_query_id)
    except Exception:
        logger.error(f"webhook error: {traceback.format_exc()}")
    return {"ok": True}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
