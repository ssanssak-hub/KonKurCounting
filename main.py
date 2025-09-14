import os
import json
import time
import logging
import jdatetime
import requests
import sqlite3
import atexit
import pytz
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Union
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

# روزهای هفته
WEEK_DAYS = {
    "شنبه": "saturday",
    "یکشنبه": "sunday", 
    "دوشنبه": "monday",
    "سهشنبه": "tuesday",
    "چهارشنبه": "wednesday",
    "پنجشنبه": "thursday",
    "جمعه": "friday",
    "همه روزها": "all"
}

# مدیریت دیتابیس
DB_FILE = "bot_data.db"

# کش برای ذخیره وضعیت عضویت کاربران
user_subscription_cache = {}

def init_db():
    """ایجاد جداول دیتابیس"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # جدول مطالعه کاربران
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_study (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            duration REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # جدول یادآوری کاربران
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_reminders (
            chat_id INTEGER PRIMARY KEY,
            enabled BOOLEAN DEFAULT FALSE,
            reminder_time TEXT DEFAULT '08:00',
            exams TEXT DEFAULT '[]',
            days TEXT DEFAULT '[]',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # جدول وضعیت عضویت کاربران
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_subscriptions (
            chat_id INTEGER PRIMARY KEY,
            subscribed BOOLEAN DEFAULT FALSE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    """مدیریت اتصال به دیتابیس"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def load_user_data():
    """بارگذاری داده‌های کاربران از دیتابیس"""
    global user_study, user_reminders, user_subscriptions
    user_study = {}
    user_reminders = {}
    user_subscriptions = {}
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # بارگذاری مطالعه کاربران
            cursor.execute("SELECT * FROM user_study")
            study_data = cursor.fetchall()
            
            for row in study_data:
                chat_id = row['chat_id']
                if chat_id not in user_study:
                    user_study[chat_id] = []
                
                user_study[chat_id].append({
                    "subject": row['subject'],
                    "start": row['start_time'],
                    "end": row['end_time'],
                    "duration": row['duration']
                })
            
            # بارگذاری یادآوری کاربران
            cursor.execute("SELECT * FROM user_reminders")
            reminder_data = cursor.fetchall()
            
            for row in reminder_data:
                user_reminders[row['chat_id']] = {
                    "enabled": bool(row['enabled']),
                    "time": row['reminder_time'],
                    "exams": json.loads(row['exams']),
                    "days": json.loads(row['days'])
                }
            
            # بارگذاری وضعیت عضویت کاربران
            cursor.execute("SELECT * FROM user_subscriptions")
            subscription_data = cursor.fetchall()
            
            for row in subscription_data:
                user_subscriptions[row['chat_id']] = bool(row['subscribed'])
        
        logger.info("✅ User data loaded from database")
        logger.info(f"📊 Loaded {len(user_reminders)} user reminders")
        logger.info(f"📊 Loaded {len(user_subscriptions)} user subscriptions")
        
    except Exception as e:
        logger.error(f"Database load error: {e}")
        user_study = {}
        user_reminders = {}
        user_subscriptions = {}

def save_user_study(chat_id, study_data):
    """ذخیره مطالعه کاربر در دیتابیس"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # حذف داده‌های قبلی و درج جدید
            cursor.execute("DELETE FROM user_study WHERE chat_id = ?", (chat_id,))
            
            for study in study_data:
                cursor.execute(
                    "INSERT INTO user_study (chat_id, subject, start_time, end_time, duration) VALUES (?, ?, ?, ?, ?)",
                    (chat_id, study['subject'], study['start'], study['end'], study['duration'])
                )
            
            conn.commit()
            
    except Exception as e:
        logger.error(f"Save study error: {e}")

def save_user_reminder(chat_id, reminder_data):
    """ذخیره تنظیمات یادآوری کاربر در دیتابیس"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            exams_json = json.dumps(reminder_data.get('exams', []), ensure_ascii=False)
            days_json = json.dumps(reminder_data.get('days', []), ensure_ascii=False)
            
            cursor.execute(
                """INSERT OR REPLACE INTO user_reminders 
                (chat_id, enabled, reminder_time, exams, days) 
                VALUES (?, ?, ?, ?, ?)""",
                (chat_id, int(reminder_data.get('enabled', False)), 
                 reminder_data.get('time', '08:00'), exams_json, days_json)
            )
            
            conn.commit()
            
    except Exception as e:
        logger.error(f"Save reminder error: {e}")

def save_user_subscription(chat_id, subscribed):
    """ذخیره وضعیت عضویت کاربر در دیتابیس"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute(
                """INSERT OR REPLACE INTO user_subscriptions 
                (chat_id, subscribed) 
                VALUES (?, ?)""",
                (chat_id, int(subscribed))
            )
            
            conn.commit()
            
    except Exception as e:
        logger.error(f"Save subscription error: {e}")

def delete_user_study(chat_id, index=None):
    """حذف مطالعه کاربر از دیتابیس"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            if index is not None:
                # پیدا کردن رکورد خاص
                cursor.execute(
                    "SELECT id FROM user_study WHERE chat_id = ? ORDER BY id LIMIT 1 OFFSET ?",
                    (chat_id, index)
                )
                record = cursor.fetchone()
                if record:
                    cursor.execute("DELETE FROM user_study WHERE id = ?", (record['id'],))
            else:
                cursor.execute("DELETE FROM user_study WHERE chat_id = ?", (chat_id,))
            
            conn.commit()
            return True
            
    except Exception as e:
        logger.error(f"Delete study error: {e}")
        return False

def delete_all_user_data(chat_id):
    """حذف تمام اطلاعات کاربر از دیتابیس"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # حذف اطلاعات مطالعه
            cursor.execute("DELETE FROM user_study WHERE chat_id = ?", (chat_id,))
            
            # حذف اطلاعات یادآوری
            cursor.execute("DELETE FROM user_reminders WHERE chat_id = ?", (chat_id,))
            
            # حذف اطلاعات عضویت
            cursor.execute("DELETE FROM user_subscriptions WHERE chat_id = ?", (chat_id,))
            
            conn.commit()
            
            # به‌روزرسانی داده‌های در حافظه
            if chat_id in user_study:
                del user_study[chat_id]
            if chat_id in user_reminders:
                del user_reminders[chat_id]
            if chat_id in user_subscriptions:
                del user_subscriptions[chat_id]
                
            logger.info(f"✅ All data deleted for user {chat_id}")
            return True
            
    except Exception as e:
        logger.error(f"Delete all user data error: {e}")
        return False

# مقداردهی اولیه دیتابیس
init_db()
load_user_data()
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
    except requests.exceptions.RequestException as e:
        logger.error(f"send_message error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in send_message: {e}")
        return None

# ویرایش پیام
def edit_message(chat_id: int, message_id: int, text: str, reply_markup: Optional[Dict] = None) -> bool:
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

    try:
        resp = requests.post(f"{TELEGRAM_API}/editMessageText", data=payload, timeout=10)
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"edit_message error: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error in edit_message: {e}")
        return False

# پاسخ به callback_query
def answer_callback_query(callback_query_id, text=""):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = False
    
    try:
        resp = requests.post(f"{TELEGRAM_API}/answerCallbackQuery", data=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"answer_callback_query error: {e}")
        return False

# اینلاین کیبورد برای عضویت در کانال
def get_channel_subscription_keyboard():
    keyboard = [
        [{
            "text": "📢 عضویت در کانال",
            "url": "https://t.me/video_amouzeshi"
        }],
        [{
            "text": "✅ بررسی عضویت",
            "callback_data": "check_subscription"
        }]
    ]
    return {"inline_keyboard": keyboard}

# بررسی عضویت کاربر در کانال
def check_user_subscription(chat_id: int, user_id: int) -> bool:
    """بررسی عضویت کاربر در کانال با کش"""
    try:
        # بررسی کش اولیه
        if user_id in user_subscription_cache:
            if time.time() - user_subscription_cache[user_id]['timestamp'] < 300:  # 5 دقیقه کش
                return user_subscription_cache[user_id]['is_member']
        
        # استفاده از Telegram API برای بررسی عضویت کاربر
        channel_id = "-1001908866403"  # آیدی کانال شما
        
        resp = requests.get(f"{TELEGRAM_API}/getChatMember", 
                           params={"chat_id": channel_id, "user_id": user_id})
        resp.raise_for_status()
        
        member_status = resp.json().get('result', {}).get('status', 'left')
        is_member = member_status in ['member', 'administrator', 'creator']
        
        # ذخیره در کش
        user_subscription_cache[user_id] = {
            'is_member': is_member,
            'timestamp': time.time()
        }
        
        return is_member
        
    except Exception as e:
        logger.error(f"Error checking subscription for user {user_id}: {e}")
        # در صورت خطا، وضعیت قبلی را بازگردان (اگر وجود دارد)
        if user_id in user_subscription_cache:
            return user_subscription_cache[user_id]['is_member']
        return False

# کیبورد اصلی با دکمه عضویت
def main_menu():
    return {
        "keyboard": [
            [{"text": "🔎 چند روز تا کنکور؟"}],
            [{"text": "📖 برنامه‌ریزی"}],
            [{"text": "⏰ مدیریت یادآوری"}],
            [{"text": "🗑️ حذف اطلاعات"}],
            [{"text": "🔄 ریستارت ربات"}],
            [{"text": "📢 عضویت در کانال"}],
        ],
        "resize_keyboard": True,
    }

# اینلاین کیبورد برای تأیید حذف اطلاعات
def get_delete_confirmation_keyboard():
    """ایجاد کیبورد اینلاین برای تأیید حذف اطلاعات"""
    keyboard = [
        [{
            "text": "✅ بله، همه اطلاعات را حذف کن",
            "callback_data": "confirm_delete_yes"
        }],
        [{
            "text": "❌ خیر، انصراف",
            "callback_data": "confirm_delete_no"
        }]
    ]
    
    return keyboard

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

# اینلاین کیبورد برای مدیریت یادآوری (مرحله اول)
def get_reminder_main_inline_keyboard():
    """ایجاد کیبورد اینلاین برای مدیریت یادآوری"""
    keyboard = [
        [{
            "text": "⚙️ تنظیم یادآوری جدید",
            "callback_data": "reminder_setup_new"
        }],
        [{
            "text": "📋 مشاهده تنظیمات فعلی",
            "callback_data": "reminder_view_settings"
        }],
        [{
            "text": "🔕 غیرفعال کردن یادآوری",
            "callback_data": "reminder_disable"
        }],
        [{
            "text": "🗑️ حذف تنظیمات یادآوری",
            "callback_data": "reminder_delete"
        }]
    ]
    
    return keyboard

# اینلاین کیبورد برای مدیریت وضعیت یادآوری (مرحله اول)
def get_status_inline_keyboard(chat_id):
    """ایجاد کیبورد اینلاین برای مدیریت وضعیت یادآوری"""
    is_enabled = user_reminders.get(chat_id, {}).get("enabled", False)
    
    keyboard = [
        [{
            "text": f"{'✅' if is_enabled else '🔲'} فعال کردن یادآوری",
            "callback_data": "reminder_status_enable"
        }],
        [{
            "text": f"{'✅' if not is_enabled else '🔲'} غیرفعال کردن یادآوری",
            "callback_data": "reminder_status_disable"
        }],
        [{
            "text": "⏭️ مرحله بعد (انتخاب کنکور)",
            "callback_data": "reminder_next_exams"
        }]
    ]
    
    return keyboard

# اینلاین کیبورد برای انتخاب کنکورها (مرحله دوم)
def get_exam_inline_keyboard(chat_id):
    """ایجاد کیبورد اینلاین برای انتخاب کنکورها"""
    selected_exams = user_reminders.get(chat_id, {}).get("exams", [])
    
    keyboard = [
        [{
            "text": f"{'✅' if 'تجربی' in selected_exams else '🔲'} تجربی",
            "callback_data": "reminder_exam_تجربی"
        }],
        [{
            "text": f"{'✅' if 'ریاضی' in selected_exams else '🔲'} ریاضی", 
            "callback_data": "reminder_exam_ریاضی"
        }],
        [{
            "text": f"{'✅' if 'انسانی' in selected_exams else '🔲'} انسانی",
            "callback_data": "reminder_exam_انسانی"
        }],
        [{
            "text": f"{'✅' if 'هنر' in selected_exams else '🔲'} هنر",
            "callback_data": "reminder_exam_هنر"
        }],
        [{
            "text": f"{'✅' if 'فرهنگیان' in selected_exams else '🔲'} فرهنگیان",
            "callback_data": "reminder_exam_فرهنگیان"
        }],
        [{
            "text": "✅ انتخاب همه",
            "callback_data": "reminder_exam_all"
        }],
        [{
            "text": "❌ حذف همه",
            "callback_data": "reminder_exam_none"
        }],
        [{
            "text": "⏭️ مرحله بعد (تنظیم زمان)",
            "callback_data": "reminder_next_time"
        }]
    ]
    
    return keyboard

# اینلاین کیبورد برای انتخاب زمان (از 00 تا 23) (مرحله سوم)
def get_time_inline_keyboard(chat_id):
    """ایجاد کیبورد اینلاین برای انتخاب زمان"""
    current_time = user_reminders.get(chat_id, {}).get("time", "08:00")
    
    # ایجاد دکمه‌های ساعت از 00 تا 23
    hours = []
    for i in range(0, 24):
        hour = f"{i:02d}"
        hours.append({
            "text": f"{'🟢' if hour == current_time.split(':')[0] else '⚪'} {hour}",
            "callback_data": f"reminder_hour_{hour}"
        })
    
    # ایجاد دکمه‌های دقیقه
    minutes = []
    for i in range(0, 60, 5):
        minute = f"{i:02d}"
        minutes.append({
            "text": f"{'🟢' if minute == current_time.split(':')[1] else '⚪'} {minute}",
            "callback_data": f"reminder_minute_{minute}"
        })
    
    # تقسیم ساعت‌ها به ردیف‌های 6 تایی برای نمایش بهتر
    keyboard = [
        [{"text": "⏰ ساعت:", "callback_data": "reminder_time_label"}],
    ]
    
    # اضافه کردن ساعت‌ها در ردیف‌های 6 تایی
    for i in range(0, 24, 6):
        keyboard.append(hours[i:i+6])
    
    keyboard.append([{"text": "⏰ دقیقه:", "callback_data": "reminder_time_label"}])
    
    # اضافه کردن دقیقه‌ها در ردیف‌های 6 تایی
    for i in range(0, len(minutes), 6):
        keyboard.append(minutes[i:i+6])
    
    keyboard.extend([
        [{
            "text": f"✅ تأیید زمان: {current_time}",
            "callback_data": "reminder_time_confirm"
        }],
        [{
            "text": "⏭️ مرحله بعد (انتخاب روزها)",
            "callback_data": "reminder_next_days"
        }]
    ])
    
    return keyboard

# اینلاین کیبورد برای انتخاب روزهای هفته (مرحله چهارم)
def get_days_inline_keyboard(chat_id):
    """ایجاد کیبورد اینلاین برای انتخاب روزهای هفته"""
    selected_days = user_reminders.get(chat_id, {}).get("days", [])
    
    keyboard = [
        [{
            "text": f"{'✅' if 'شنبه' in selected_days else '🔲'} شنبه",
            "callback_data": "reminder_day_شنبه"
        }],
        [{
            "text": f"{'✅' if 'یکشنبه' in selected_days else '🔲'} یکشنبه",
            "callback_data": "reminder_day_یکشنبه"
        }],
        [{
            "text": f"{'✅' if 'دوشنبه' in selected_days else '🔲'} دوشنبه",
            "callback_data": "reminder_day_دوشنبه"
        }],
        [{
            "text": f"{'✅' if 'سهشنبه' in selected_days else '🔲'} سهشنبه",
            "callback_data": "reminder_day_سهشنبه"
        }],
        [{
            "text": f"{'✅' if 'چهارشنبه' in selected_days else '🔲'} چهارشنبه",
            "callback_data": "reminder_day_چهارشنبه"
        }],
        [{
            "text": f"{'✅' if 'پنجشنبه' in selected_days else '🔲'} پنجشنبه",
            "callback_data": "reminder_day_پنجشنبه"
        }],
        [{
            "text": f"{'✅' if 'جمعه' in selected_days else '🔲'} جمعه",
            "callback_data": "reminder_day_جمعه"
        }],
        [{
            "text": "✅ همه روزها",
            "callback_data": "reminder_day_all"
        }],
        [{
            "text": "❌ حذف همه",
            "callback_data": "reminder_day_none"
        }],
        [{
            "text": "✅ ذخیره و تکمیل تنظیمات",
            "callback_data": "reminder_status_save"
        }]
    ]
    
    return keyboard

# اینلاین کیبورد برای مدیریت وضعیت یادآوری (مرحله نهایی)
def get_final_status_inline_keyboard(chat_id):
    """ایجاد کیبورد اینلاین برای مدیریت وضعیت یادآوری"""
    is_enabled = user_reminders.get(chat_id, {}).get("enabled", False)
    
    keyboard = [
        [{
            "text": f"{'✅' if is_enabled else '🔲'} فعال کردن یادآوری",
            "callback_data": "reminder_status_enable"
        }],
        [{
            "text": f"{'✅' if not is_enabled else '🔲'} غیرفعال کردن یادآوری",
            "callback_data": "reminder_status_disable"
        }],
        [{
            "text": "🗑️ حذف همه تنظیمات یادآوری",
            "callback_data": "reminder_status_delete"
        }],
        [{
            "text": "✅ ذخیره و تکمیل تنظیمات",
            "callback_data": "reminder_status_save"
        }]
    ]
    
    return keyboard

# ارسال یادآوری به کاربر
def send_reminder_to_user(chat_id: int) -> bool:
    """ارسال یادآوری کنکور به کاربر خاص"""
    try:
        if chat_id not in user_reminders:
            logger.warning(f"User {chat_id} not found in reminders")
            return False
        
        settings = user_reminders[chat_id]
        if not settings.get("enabled", False):
            logger.warning(f"Reminders disabled for user {chat_id}")
            return False
        
        user_exams = settings.get("exams", [])
        if not user_exams:
            logger.warning(f"No exams selected for user {chat_id}")
            return False
        
        reminder_text = "⏰ یادآوری روزانه کنکور:\n\n"
        for exam_name in user_exams:
            if exam_name in EXAMS:
                reminder_text += get_countdown(exam_name) + "\n\n"
        
        if reminder_text == "⏰ یادآوری روزانه کنکور:\n\n":
            reminder_text = "⏰ امروز کنکوری برای یادآوری ندارید!"
        
        success = send_message(chat_id, reminder_text)
        if success:
            logger.info(f"✅ یادآوری ارسال شد به کاربر {chat_id}")
        else:
            logger.error(f"❌ Failed to send reminder to user {chat_id}")
        
        return success
        
    except Exception as e:
        logger.error(f"Error in send_reminder_to_user for {chat_id}: {e}")
        return False

# محاسبه تایمر (نسخه اصلاح شده)
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

# تابع برای گرفتن زمان ایران
def get_iran_time() -> str:
    """دریافت زمان فعلی ایران با فرمت یکسان"""
    try:
        iran_time = datetime.now(IRAN_TZ)
        return iran_time.strftime("%H:%M")  # همیشه با فرمت 00:00
    except Exception as e:
        logger.error(f"Error getting Iran time: {e}")
        return datetime.now().strftime("%H:%M")

# تابع ارسال یادآوری روزانه
def send_daily_reminders():
    """ارسال یادآوری روزانه به همه کاربران"""
    try:
        now_iran = get_iran_time()
        logger.info(f"🔔 Checking reminders at Iran time: {now_iran}")
        logger.info(f"📊 Total users with reminders: {len(user_reminders)}")
        
        # همچنین بررسی روز هفته
        today_name = jdatetime.datetime.now().strftime("%A")
        today_persian = list(WEEK_DAYS.keys())[list(WEEK_DAYS.values()).index(today_name.lower())]
        
        active_reminders = 0
        for chat_id, settings in user_reminders.items():
            user_time = settings.get("time", "08:00")
            user_enabled = settings.get("enabled", False)
            user_exams = settings.get("exams", [])
            user_days = settings.get("days", [])
            
            # بررسی آیا امروز روز انتخابی کاربر است
            today_selected = "همه روزها" in user_days or today_persian in user_days
            
            logger.info(f"User {chat_id}: time={user_time}, enabled={user_enabled}, today_selected={today_selected}")
            
            if (user_enabled and user_time == now_iran and user_exams and today_selected):
                logger.info(f"⏰ Sending reminder to {chat_id} at {now_iran}")
                if send_reminder_to_user(chat_id):
                    active_reminders += 1
                # تاخیر کوچک بین ارسال به کاربران مختلف
                time.sleep(0.5)
        
        logger.info(f"✅ Sent reminders to {active_reminders} users")
                
    except Exception as e:
        logger.error(f"Reminder scheduler error: {e}")

# تابع ارسال یادآوری خودکار
def send_automatic_reminders():
    """ارسال یادآوری خودکار ساعت 8 صبح و 10 شب"""
    try:
        now_iran = get_iran_time()
        logger.info(f"🔔 Checking automatic reminders at Iran time: {now_iran}")
        
        # بررسی زمان (8 صبح یا 10 شب)
        if now_iran in ["08:00", "22:00"]:
            logger.info(f"⏰ Time for automatic reminder: {now_iran}")
            
            for chat_id, settings in user_reminders.items():
                user_enabled = settings.get("enabled", False)
                user_exams = settings.get("exams", [])
                
                if user_enabled and user_exams:
                    logger.info(f"📨 Sending automatic reminder to {chat_id}")
                    
                    reminder_text = f"⏰ یادآوری { 'صبح' if now_iran == '08:00' else 'شب' }:\n\n"
                    for exam_name in user_exams:
                        if exam_name in EXAMS:
                            reminder_text += get_countdown(exam_name) + "\n\n"
                    
                    if reminder_text != f"⏰ یادآوری { 'صبح' if now_iran == '08:00' else 'شب' }:\n\n":
                        send_message(chat_id, reminder_text)
                        time.sleep(0.5)  # تاخیر بین ارسال به کاربران مختلف
                    
            logger.info(f"✅ Sent automatic reminders at {now_iran}")
                
    except Exception as e:
        logger.error(f"Automatic reminder scheduler error: {e}")

# نمایش تنظیمات کاربر
def show_user_settings(chat_id: int) -> str:
    """نمایش تنظیمات کاربر"""
    if chat_id not in user_reminders:
        return "🔕 شما هنوز سیستم یادآوری را فعال نکرده‌اید."
    
    settings = user_reminders[chat_id]
    enabled = settings.get("enabled", False)
    time_str = settings.get("time", "08:00")
    exams = settings.get("exams", [])
    days = settings.get("days", [])
    
    status = "✅ فعال" if enabled else "❌ غیرفعال"
    exams_text = ", ".join(exams) if exams else "هیچکدام"
    days_text = ", ".join(days) if days else "هیچکدام"
    
    return (
        f"🔧 تنظیمات یادآوری شما:\n\n"
        f"• 🕐 زمان: {time_str}\n"
        f"• 📚 کنکورها: {exams_text}\n"
        f"• 📅 روزها: {days_text}\n"
        f"• 📊 وضعیت: {status}\n\n"
        f"برای تغییر تنظیمات از منوی زیر استفاده کنید:"
    )

# تابع ریستارت (شبیه به /start)
def restart_bot_for_user(chat_id: int):
    """ریستارت ربات برای کاربر - عملکرد شبیه به /start"""
    try:
        # ارسال پیام خوش‌آمدگویی مجدد بدون پاک کردن اطلاعات
        send_message(
            chat_id,
            "🔄 ربات با موفقیت ریستارت شد!\n\n"
            "سلام 👋 دوباره به ربات کنکور خوش آمدید!\n"
            "یک گزینه رو انتخاب کن:",
            reply_markup=main_menu()
        )
        logger.info(f"✅ Bot restarted for user {chat_id} (no data cleared)")
        
    except Exception as e:
        logger.error(f"❌ Error in restart_bot_for_user: {e}")
        send_message(chat_id, "⚠️ خطایی در ریستارت ربات occurred. لطفاً دوباره تلاش کنید.", reply_markup=main_menu())

# هندلرهای پیام‌ها
def handle_start(chat_id: int, user_id: int):
    """مدیریت دستور شروع"""
    send_message(chat_id, "سلام 👋 یک گزینه رو انتخاب کن:", reply_markup=main_menu())

def handle_countdown(chat_id: int):
    """مدیریت نمایش زمان تا کنکور"""
    send_message(chat_id, "یک کنکور رو انتخاب کن:", reply_markup=exam_menu())

def handle_study(chat_id: int):
    """مدیریت بخش برنامه‌ریزی"""
    send_message(chat_id, "📖 بخش برنامه‌ریزی:", reply_markup=study_menu())

def handle_reminder_menu(chat_id: int):
    """مدیریت منوی یادآوری"""
    text = "⏰ مدیریت یادآوری:\n\nلطفاً یکی از گزینه‌های زیر را انتخاب کنید:"
    message_id = send_message(chat_id, text, {"inline_keyboard": get_reminder_main_inline_keyboard()})
    
    if message_id:
        user_message_ids[chat_id] = message_id

def handle_add_study(chat_id: int):
    """ثبت مطالعه"""
    send_message(
        chat_id,
        "📚 لطفاً اطلاعات مطالعه را به این شکل وارد کنید:\n\n"
        "نام درس، ساعت شروع (hh:mm)، ساعت پایان (hh:mm)، مدت (ساعت)\n\n"
        "مثال:\nریاضی، 14:00، 16:00، 2",
        reply_markup=study_menu()
    )

def handle_view_progress(chat_id: int):
    """مشاهده پیشرفت"""
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

def handle_delete_study(chat_id: int):
    """حذف مطالعه"""
    logs = user_study.get(chat_id, [])
    if not logs:
        send_message(chat_id, "📭 چیزی برای حذف وجود نداره.", reply_markup=study_menu())
    else:
        for idx, e in enumerate(logs):
            msg = f"• {e['subject']} | {e['start']} تا {e['end']} | {e['duration']} ساعت"
            inline_kb = [[{"text": "❌ حذف", "callback_data": f"delete_{idx}"}]]
            send_message(chat_id, msg, {"inline_keyboard": inline_kb})

def handle_delete_data(chat_id: int):
    """مدیریت حذف اطلاعات"""
    text = "⚠️ <b>حذف همه اطلاعات</b>\n\nآیا مطمئن هستید که می‌خواهید همه اطلاعات خود را حذف کنید؟\n\nاین عمل شامل تمام اطلاعات مطالعه و تنظیمات یادآوری شما می‌شود و غیرقابل بازگشت است!"
    send_message(chat_id, text, {"inline_keyboard": get_delete_confirmation_keyboard()})

def handle_channel_subscription(chat_id: int):
    """مدیریت عضویت در کانال"""
    send_message(
        chat_id,
        "📢 برای عضویت در کانال آموزشی ما:\n\n"
        "لطفاً روی دکمه زیر کلیک کرده و در کانال عضو شوید، سپس روی '✅ بررسی عضویت' کلیک کنید.",
        reply_markup=get_channel_subscription_keyboard()
    )

# ذخیره message_id برای ویرایش پیام
user_message_ids = {}

def handle_back(chat_id: int):
    """بازگشت به منوی اصلی"""
    if chat_id in user_message_ids:
        del user_message_ids[chat_id]
    send_message(chat_id, "↩️ بازگشتی به منوی اصلی:", reply_markup=main_menu())

def handle_study_input(chat_id: int, text: str):
    """مدیریت ورودی مطالعه"""
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
            
            save_user_study(chat_id, user_study[chat_id])
            send_message(chat_id, f"✅ مطالعه {subject} از {start_time} تا {end_time} به مدت {duration} ساعت ثبت شد.", reply_markup=study_menu())
        else:
            send_message(chat_id, "❌ فرمت اشتباه است. لطفاً دوباره وارد کن.", reply_markup=study_menu())
    except Exception as e:
        logger.error(f"Study parse error: {e}")
        send_message(chat_id, "⚠️ مشکلی در ثبت پیش آمد. دوباره امتحان کن.", reply_markup=study_menu())

# هندلرهای callback
def handle_reminder_status_callback(chat_id: int, status: str, message_id: int):
    """مدیریت وضعیت یادآوری"""
    if chat_id not in user_reminders:
        user_reminders[chat_id] = {"enabled": False, "time": "08:00", "exams": [], "days": []}
    
    if status == "enable":
        user_reminders[chat_id]["enabled"] = True
        message = "✅ یادآوری فعال شد"
    elif status == "disable":
        user_reminders[chat_id]["enabled"] = False
        message = "❌ یادآوری غیرفعال شد"
    elif status == "delete":
        user_reminders[chat_id] = {"enabled": False, "time": "08:00", "exams": [], "days": []}
        message = "🗑️ همه تنظیمات یادآوری حذف شد"
    
    save_user_reminder(chat_id, user_reminders[chat_id])
    
    # ویرایش پیام با کیبورد به‌روز شده
    text = "🔔 مدیریت یادآوری:\n\nلطفاً وضعیت یادآوری را انتخاب کنید:"
    edit_message(chat_id, message_id, text, {"inline_keyboard": get_status_inline_keyboard(chat_id)})

def handle_reminder_exam_callback(chat_id: int, exam_name: str, message_id: int):
    """مدیریت انتخاب کنکور در یادآوری"""
    if chat_id not in user_reminders:
        user_reminders[chat_id] = {"enabled": False, "time": "08:00", "exams": [], "days": []}
    
    if exam_name == "all":
        # انتخاب همه کنکورها
        user_reminders[chat_id]["exams"] = list(EXAMS.keys())
    elif exam_name == "none":
        # حذف همه کنکورها
        user_reminders[chat_id]["exams"] = []
    elif exam_name in user_reminders[chat_id]["exams"]:
        # حذف کنکور اگر قبلاً انتخاب شده
        user_reminders[chat_id]["exams"].remove(exam_name)
    else:
        # افزودن کنکور
        user_reminders[chat_id]["exams"].append(exam_name)
    
    save_user_reminder(chat_id, user_reminders[chat_id])
    
    # ویرایش پیام با کیبورد به‌روز شده
    text = "🔔 مدیریت یادآوری:\n\nلطفاً کنکورهای مورد نظر خود را انتخاب کنید:"
    edit_message(chat_id, message_id, text, {"inline_keyboard": get_exam_inline_keyboard(chat_id)})

def handle_reminder_time_callback(chat_id: int, time_type: str, value: str, message_id: int):
    """مدیریت انتخاب زمان در یادآوری"""
    if chat_id not in user_reminders:
        user_reminders[chat_id] = {"enabled": False, "time": "08:00", "exams": [], "days": []}
    
    current_time = user_reminders[chat_id].get("time", "08:00").split(":")
    
    if time_type == "hour":
        current_time[0] = value
    elif time_type == "minute":
        current_time[1] = value
    
    user_reminders[chat_id]["time"] = f"{current_time[0]}:{current_time[1]}"
    save_user_reminder(chat_id, user_reminders[chat_id])
    
    # ویرایش پیام با کیبورد به‌روز شده
    text = "🔔 مدیریت یادآوری:\n\nلطفاً زمان یادآوری را انتخاب کنید:"
    edit_message(chat_id, message_id, text, {"inline_keyboard": get_time_inline_keyboard(chat_id)})

def handle_reminder_day_callback(chat_id: int, day_name: str, message_id: int):
    """مدیریت انتخاب روز در یادآوری"""
    if chat_id not in user_reminders:
        user_reminders[chat_id] = {"enabled": False, "time": "08:00", "exams": [], "days": []}
    
    if day_name == "all":
        # انتخاب همه روزها
        user_reminders[chat_id]["days"] = list(WEEK_DAYS.keys())[:-1]  # همه روزها به جز "همه روزها"
    elif day_name == "none":
        # حذف همه روزها
        user_reminders[chat_id]["days"] = []
    elif day_name in user_reminders[chat_id]["days"]:
        # حذف روز اگر قبلاً انتخاب شده
        user_reminders[chat_id]["days"].remove(day_name)
    else:
        # افزودن روز
        user_reminders[chat_id]["days"].append(day_name)
    
    save_user_reminder(chat_id, user_reminders[chat_id])
    
    # ویرایش پیام با کیبورد به‌روز شده
    text = "🔔 مدیریت یادآوری:\n\nلطفاً روزهای مورد نظر خود را انتخاب کنید:"
    edit_message(chat_id, message_id, text, {"inline_keyboard": get_days_inline_keyboard(chat_id)})

def handle_reminder_final_callback(chat_id: int, status: str, message_id: int):
    """مدیریت وضعیت نهایی یادآوری"""
    if chat_id not in user_reminders:
        user_reminders[chat_id] = {"enabled": False, "time": "08:00", "exams": [], "days": []}
    
    if status == "enable":
        user_reminders[chat_id]["enabled"] = True
        message = "✅ یادآوری فعال شد"
    elif status == "disable":
        user_reminders[chat_id]["enabled"] = False
        message = "❌ یادآوری غیرفعال شد"
    elif status == "delete":
        user_reminders[chat_id] = {"enabled": False, "time": "08:00", "exams": [], "days": []}
        message = "🗑️ همه تنظیمات یادآوری حذف شد"
    elif status == "save":
        message = "✅ تنظیمات یادآوری ذخیره شد"
    
    save_user_reminder(chat_id, user_reminders[chat_id])
    
    if status != "save":
        # ویرایش پیام با کیبورد به‌روز شده
        text = "🔔 مدیریت یادآوری:\n\nلطفاً وضعیت یادآوری را انتخاب کنید:"
        edit_message(chat_id, message_id, text, {"inline_keyboard": get_final_status_inline_keyboard(chat_id)})
    else:
        # حذف پیام و ارسال پیام جدید
        edit_message(chat_id, message_id, "✅ تنظیمات یادآوری شما با موفقیت ذخیره شد.")
        if chat_id in user_message_ids:
            del user_message_ids[chat_id]
        send_message(chat_id, message, reply_markup=main_menu())

def handle_delete_confirmation(chat_id: int, confirm: bool, message_id: int):
    """مدیریت تأیید حذف اطلاعات"""
    if confirm:
        if delete_all_user_data(chat_id):
            text = "✅ همه اطلاعات شما با موفقیت حذف شد."
        else:
            text = "❌ خطایی در حذف اطلاعات رخ داد."
    else:
        text = "✅ عمل حذف اطلاعات لغو شد."
    
    edit_message(chat_id, message_id, text)
    send_message(chat_id, "↩️ بازگشتی به منوی اصلی:", reply_markup=main_menu())

def handle_subscription_check(chat_id: int, user_id: int, callback_id: int, message_id: int):
    """مدیریت بررسی عضویت کاربر"""
    # بررسی عضویت کاربر
    is_member = check_user_subscription(chat_id, user_id)
    
    if is_member:
        # ذخیره وضعیت عضویت
        user_subscriptions[chat_id] = True
        save_user_subscription(chat_id, True)
        
        # پاکسازی کش برای این کاربر
        if user_id in user_subscription_cache:
            del user_subscription_cache[user_id]
        
        # ویرایش پیام و ارسال منوی اصلی
        edit_message(chat_id, message_id, "✅ شما با موفقیت در کانال عضو شدید! اکنون می‌توانید از ربات استفاده کنید.")
        send_message(chat_id, "سلام 👋 یک گزینه رو انتخاب کن:", reply_markup=main_menu())
    else:
        # کاربر هنوز عضو نشده
        answer_callback_query(callback_id, "❌ شما هنوز در کانال عضو نشده‌اید. لطفاً ابتدا در کانال عضو شوید.")
        
        # ارسال پیام جدید با کیبورد عضویت
        send_message(
            chat_id,
            "❌ شما هنوز در کانال عضو نشده‌اید.\n\n"
            "لطفاً روی دکمه زیر کلیک کرده و در کانال عضو شوید، سپس روی '✅ بررسی عضویت' کلیک کنید.",
            reply_markup=get_channel_subscription_keyboard()
        )

def handle_reminder_main_callback(chat_id: int, callback_data: str, message_id: int):
    """مدیریت callback منوی اصلی یادآوری"""
    try:
        if callback_data == "reminder_setup_new":
            text = "🔔 مدیریت یادآوری:\n\nلطفاً وضعیت یادآوری را انتخاب کنید:"
            edit_message(chat_id, message_id, text, {"inline_keyboard": get_status_inline_keyboard(chat_id)})
            
        elif callback_data == "reminder_view_settings":
            settings_text = show_user_settings(chat_id)
            edit_message(chat_id, message_id, settings_text, {"inline_keyboard": get_reminder_main_inline_keyboard()})
            
        elif callback_data == "reminder_disable":
            if chat_id in user_reminders:
                user_reminders[chat_id]["enabled"] = False
                save_user_reminder(chat_id, user_reminders[chat_id])
                edit_message(chat_id, message_id, "✅ یادآوری غیرفعال شد.", {"inline_keyboard": get_reminder_main_inline_keyboard()})
            else:
                edit_message(chat_id, message_id, "🔕 شما هنوز سیستم یادآوری را فعال نکرده‌اید.", {"inline_keyboard": get_reminder_main_inline_keyboard()})
                
        elif callback_data == "reminder_delete":
            if chat_id in user_reminders:
                user_reminders[chat_id] = {"enabled": False, "time": "08:00", "exams": [], "days": []}
                save_user_reminder(chat_id, user_reminders[chat_id])
                edit_message(chat_id, message_id, "🗑️ همه تنظیمات یادآوری حذف شد.", {"inline_keyboard": get_reminder_main_inline_keyboard()})
            else:
                edit_message(chat_id, message_id, "🔕 شما هنوز سیستم یادآوری را فعال نکرده‌اید.", {"inline_keyboard": get_reminder_main_inline_keyboard()})
                
    except Exception as e:
        logger.error(f"Error in handle_reminder_main_callback: {e}")

# هندل پیام‌ها
def handle_message(chat_id: int, user_id: int, text: str):
    # نگاشت دستورات به توابع مربوطه
    command_handlers = {
        "شروع": lambda: handle_start(chat_id, user_id),
        "/start": lambda: handle_start(chat_id, user_id),
        "🔄 ریستارت ربات": lambda: restart_bot_for_user(chat_id),
        "🔎 چند روز تا کنکور؟": lambda: handle_countdown(chat_id),
        "📖 برنامه‌ریزی": lambda: handle_study(chat_id),
        "⏰ مدیریت یادآوری": lambda: handle_reminder_menu(chat_id),
        "🗑️ حذف اطلاعات": lambda: handle_delete_data(chat_id),
        "📢 عضویت در کانال": lambda: handle_channel_subscription(chat_id),
        "➕ ثبت مطالعه": lambda: handle_add_study(chat_id),
        "📊 مشاهده پیشرفت": lambda: handle_view_progress(chat_id),
        "🗑️ حذف مطالعه": lambda: handle_delete_study(chat_id),
        "⬅️ بازگشت": lambda: handle_back(chat_id),
    }
    
    # بررسی اگر دستور مستقیم وجود دارد
    if text in command_handlers:
        command_handlers[text]()
        return
    
    # بررسی اگر نمایش زمان کنکور است
    exam_handlers = {
        "🧪 کنکور تجربی": lambda: send_message(chat_id, get_countdown("تجربی")),
        "📐 کنکور ریاضی": lambda: send_message(chat_id, get_countdown("ریاضی")),
        "📚 کنکور انسانی": lambda: send_message(chat_id, get_countdown("انسانی")),
        "🎨 کنکور هنر": lambda: send_message(chat_id, get_countdown("هنر")),
        "🏫 کنکور فرهنگیان": lambda: send_message(chat_id, get_countdown("فرهنگیان")),
    }
    
    if text in exam_handlers:
        exam_handlers[text]()
        return
    
    # بررسی اگر ورودی مطالعه است
    try:
        parts = [p.strip() for p in text.split("،")]
        if len(parts) == 4:
            handle_study_input(chat_id, text)
            return
    except:
        pass
    
    # اگر هیچکدام منوی بالا نبود
    send_message(chat_id, "❌ دستور نامعتبر است. لطفاً از منو استفاده کنید.", reply_markup=main_menu())

# هندل callback queries
def handle_callback_query(chat_id: int, user_id: int, callback_data: str, callback_id: int, message_id: int):
    try:
        # پاسخ دادن به callback query
        answer_callback_query(callback_id)
        
        if callback_data == "check_subscription":
            handle_subscription_check(chat_id, user_id, callback_id, message_id)
            
        elif callback_data in ["reminder_setup_new", "reminder_view_settings", "reminder_disable", "reminder_delete"]:
            handle_reminder_main_callback(chat_id, callback_data, message_id)
            
        elif callback_data.startswith("reminder_status_"):
            status = callback_data.replace("reminder_status_", "")
            handle_reminder_status_callback(chat_id, status, message_id)
            
        elif callback_data == "reminder_next_exams":
            text = "🔔 مدیریت یادآوری:\n\nلطفاً کنکورهای مورد نظر خود را انتخاب کنید:"
            edit_message(chat_id, message_id, text, {"inline_keyboard": get_exam_inline_keyboard(chat_id)})
            
        elif callback_data.startswith("reminder_exam_"):
            exam_name = callback_data.replace("reminder_exam_", "")
            handle_reminder_exam_callback(chat_id, exam_name, message_id)
            
        elif callback_data == "reminder_next_time":
            text = "🔔 مدیریت یادآوری:\n\nلطفاً زمان یادآوری را انتخاب کنید:"
            edit_message(chat_id, message_id, text, {"inline_keyboard": get_time_inline_keyboard(chat_id)})
            
        elif callback_data.startswith("reminder_hour_"):
            hour = callback_data.replace("reminder_hour_", "")
            handle_reminder_time_callback(chat_id, "hour", hour, message_id)
            
        elif callback_data.startswith("reminder_minute_"):
            minute = callback_data.replace("reminder_minute_", "")
            handle_reminder_time_callback(chat_id, "minute", minute, message_id)
            
        elif callback_data == "reminder_time_confirm":
            text = "🔔 مدیریت یادآوری:\n\nلطفاً روزهای مورد نظر خود را انتخاب کنید:"
            edit_message(chat_id, message_id, text, {"inline_keyboard": get_days_inline_keyboard(chat_id)})
            
        elif callback_data == "reminder_next_days":
            text = "🔔 مدیریت یادآوری:\n\nلطفاً روزهای مورد نظر خود را انتخاب کنید:"
            edit_message(chat_id, message_id, text, {"inline_keyboard": get_days_inline_keyboard(chat_id)})
            
        elif callback_data.startswith("reminder_day_"):
            day_name = callback_data.replace("reminder_day_", "")
            handle_reminder_day_callback(chat_id, day_name, message_id)
            
        elif callback_data == "reminder_next_status":
            text = "🔔 مدیریت یادآوری:\n\nلطفاً وضعیت نهایی یادآوری را انتخاب کنید:"
            edit_message(chat_id, message_id, text, {"inline_keyboard": get_final_status_inline_keyboard(chat_id)})
            
        elif callback_data.startswith("reminder_final_"):
            status = callback_data.replace("reminder_final_", "")
            handle_reminder_final_callback(chat_id, status, message_id)
            
        elif callback_data == "reminder_back_status":
            text = "🔔 مدیریت یادآوری:\n\nلطفاً وضعیت یادآوری را انتخاب کنید:"
            edit_message(chat_id, message_id, text, {"inline_keyboard": get_status_inline_keyboard(chat_id)})
            
        elif callback_data == "reminder_back_exams":
            text = "🔔 مدیریت یادآوری:\n\nلطفاً کنکورهای مورد نظر خود را انتخاب کنید:"
            edit_message(chat_id, message_id, text, {"inline_keyboard": get_exam_inline_keyboard(chat_id)})
            
        elif callback_data == "reminder_back_time":
            text = "🔔 مدیریت یادآوری:\n\nلطفاً زمان یادآوری را انتخاب کنید:"
            edit_message(chat_id, message_id, text, {"inline_keyboard": get_time_inline_keyboard(chat_id)})
            
        elif callback_data == "reminder_back_days":
            text = "🔔 مدیریت یادآوری:\n\nلطفاً روزهای مورد نظر خود را انتخاب کنید:"
            edit_message(chat_id, message_id, text, {"inline_keyboard": get_days_inline_keyboard(chat_id)})
            
        elif callback_data == "reminder_back_main":
            # حذف پیام و بازگشت به منوی اصلی
            edit_message(chat_id, message_id, "↩️ بازگشتی به منوی اصلی:")
            if chat_id in user_message_ids:
                del user_message_ids[chat_id]
            send_message(chat_id, "↩️ بازگشتی به منوی اصلی:", reply_markup=main_menu())
            
        elif callback_data == "confirm_delete_yes":
            handle_delete_confirmation(chat_id, True, message_id)
            
        elif callback_data == "confirm_delete_no":
            handle_delete_confirmation(chat_id, False, message_id)
            
        elif callback_data.startswith("delete_"):
            idx = int(callback_data.split("_")[1])
            if chat_id in user_study and 0 <= idx < len(user_study[chat_id]):
                removed = user_study[chat_id].pop(idx)
                delete_user_study(chat_id, idx)
                send_message(chat_id, f"🗑️ مطالعه {removed['subject']} حذف شد.", reply_markup=study_menu())
                
    except Exception as e:
        logger.error(f"Error handling callback: {e}")

# وب‌هوک
@app.route(f"/webhook/{TOKEN}", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        if not data:
            logger.warning("Empty webhook data received")
            return "ok"
        
        logger.info(f"📩 Update: {data}")

        if "callback_query" in data:
            cq = data["callback_query"]
            if "message" not in cq or "chat" not in cq["message"]:
                logger.warning("Invalid callback_query format")
                return "ok"
                
            chat_id = cq["message"]["chat"]["id"]
            user_id = cq["from"]["id"]
            cq_data = cq.get("data", "")
            cq_id = cq.get("id", "")
            message_id = cq["message"]["message_id"]
            
            handle_callback_query(chat_id, user_id, cq_data, cq_id, message_id)

        elif "message" in data and "text" in data["message"]:
            chat_id = data["message"]["chat"]["id"]
            user_id = data["message"]["from"]["id"]
            text = data["message"]["text"]
            handle_message(chat_id, user_id, text)
            
    except Exception as e:
        logger.error(f"webhook error: {e}")
    return "ok"

# scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(send_daily_reminders, 'interval', minutes=1)  # بررسی دقیقه‌ای برای یادآوری روزانه
scheduler.add_job(send_automatic_reminders, 'cron', hour='8,22', minute=0)  # فقط ساعت 8 و 22 برای یادآوری خودکار
scheduler.start()

# ست وبهوک
@app.route("/set_webhook")
def set_webhook():
    url = os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXternal_URL")
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
        
        # راه‌اندازی scheduler
        scheduler = BackgroundScheduler()
        scheduler.add_job(send_daily_reminders, 'interval', minutes=1)
        scheduler.add_job(send_automatic_reminders, 'cron', hour='8,22', minute=0)
        scheduler.start()
        logger.info("✅ Scheduler started successfully")
        
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
    finally:
        scheduler.shutdown()
