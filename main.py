import os
import logging
import jdatetime
import sqlite3
import atexit
import pytz
import re
from datetime import datetime
from typing import Optional, Dict
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import contextmanager
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackContext

# Load .env
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set in environment")

# Flask app را حذف می‌کنیم چون از telegram.ext استفاده می‌کنیم

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
    "هنر": [{"date": jdatetime.datetime(1405, 4, 12, 14, 30), "time": "14:30 عصر"}],
    "فرهنگیان": [
        {"date": jdatetime.datetime(1405, 2, 17, 8, 0), "time": "08:00 صبح"},
        {"date": jdatetime.datetime(1405, 2, 18, 8, 0), "time": "08:00 صبح"},
    ],
}

# زمان ایران
IRAN_TZ = pytz.timezone('Asia/Tehran')

# مدیریت دیتابیس
DB_FILE = "bot_data.db"

# مدیریت حالت کاربران
user_states = {}

class UserState:
    NORMAL = "normal"
    WAITING_EXAM = "waiting_exam"
    WAITING_TIME = "waiting_time"

def set_user_state(chat_id, state, data=None):
    user_states[chat_id] = {"state": state, "data": data}

def get_user_state(chat_id):
    return user_states.get(chat_id, {"state": UserState.NORMAL, "data": None})

def clear_user_state(chat_id):
    if chat_id in user_states:
        del user_states[chat_id]

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
    return ReplyKeyboardMarkup([
        ["🔎 چند روز تا کنکور؟"],
        ["📖 برنامه‌ریزی"],
        ["⏰ تنظیم یادآوری"],
        ["❌ حذف یادآوری", "❌ لغو عملیات"],
        ["🗑️ حذف اطلاعات", "🔄 ریستارت ربات"],
        ["📢 عضویت در کانال"]
    ], resize_keyboard=True)

# انتخاب کنکور
def exam_menu():
    return ReplyKeyboardMarkup([
        ["🧪 کنکور تجربی", "📐 کنکور ریاضی"],
        ["📚 کنکور انسانی", "🎨 کنکور هنر"],
        ["🏫 کنکور فرهنگیان"],
        ["⬅️ بازگشت"]
    ], resize_keyboard=True)

# اعتبارسنجی زمان
def is_valid_time(time_str):
    """اعتبارسنجی کامل فرمت زمان"""
    try:
        if not re.match(r'^\d{1,2}:\d{2}$', time_str):
            return False
        
        hours, minutes = map(int, time_str.split(':'))
        return 0 <= hours <= 23 and 0 <= minutes <= 59
    except:
        return False

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
async def send_reminders(context: CallbackContext):
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
                    await context.bot.send_message(
                        chat_id=chat_id, 
                        text=f"⏰ یادآوری امروز:\n\n{get_countdown(exam)}",
                        parse_mode="HTML"
                    )
    except Exception as e:
        logger.error(f"send_reminders error: {e}")

# هندلر شروع
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    clear_user_state(chat_id)
    await update.message.reply_text(
        "سلام 👋 یک گزینه رو انتخاب کن:",
        reply_markup=main_menu()
    )

# هندلر پیام‌های متنی
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        text = update.message.text
        user_id = update.effective_user.id
        
        logger.info(f"Received message from {chat_id}: {text}")
        
        # پردازش دستورات عمومی که در هر state ای باید کار کنند
        if text in ["شروع", "/start"]:
            await start(update, context)
            return

        if text == "❌ لغو عملیات":
            clear_user_state(chat_id)
            await update.message.reply_text(
                "✅ عملیات کنونی لغو شد.",
                reply_markup=main_menu()
            )
            return

        if text == "⬅️ بازگشت":
            clear_user_state(chat_id)
            await update.message.reply_text(
                "↩️ بازگشتی به منوی اصلی:",
                reply_markup=main_menu()
            )
            return

        state = get_user_state(chat_id)
        
        if state["state"] == UserState.WAITING_EXAM:
            exam = text.replace("کنکور ", "").strip()
            if exam in EXAMS:
                set_user_state(chat_id, UserState.WAITING_TIME, exam)
                await update.message.reply_text(
                    "⏰ لطفاً ساعت یادآوری را به فرمت HH:MM وارد کنید (مثال: 14:30):"
                )
            else:
                await update.message.reply_text(
                    "❌ لطفاً یک کنکور معتبر انتخاب کنید.",
                    reply_markup=exam_menu()
                )
            return

        if state["state"] == UserState.WAITING_TIME:
            time_input = text.strip()
            if is_valid_time(time_input):
                exam = state["data"]
                save_reminder(chat_id, exam, time_input)
                clear_user_state(chat_id)
                await update.message.reply_text(
                    f"✅ یادآوری برای کنکور {exam} در ساعت {time_input} تنظیم شد.",
                    reply_markup=main_menu()
                )
            else:
                await update.message.reply_text(
                    "❌ فرمت زمان نامعتبر است. لطفاً زمان را به فرمت HH:MM وارد کنید (مثال: 14:30):"
                )
            return

        # اگر state کاربر NORMAL است، دستورات عادی را پردازش می‌کنیم
        if text == "🔎 چند روز تا کنکور؟":
            await update.message.reply_text(
                "یک کنکور رو انتخاب کن:",
                reply_markup=exam_menu()
            )
        elif text in ["🧪 کنکور تجربی", "📐 کنکور ریاضی", "📚 کنکور انسانی", "🎨 کنکور هنر", "🏫 کنکور فرهنگیان"]:
            exam = text.replace("کنکور ", "").strip()
            await update.message.reply_text(
                get_countdown(exam),
                parse_mode="HTML"
            )
        elif text == "⏰ تنظیم یادآوری":
            set_user_state(chat_id, UserState.WAITING_EXAM)
            await update.message.reply_text(
                "📚 لطفاً یک کنکور رو انتخاب کن:",
                reply_markup=exam_menu()
            )
        elif text == "❌ حذف یادآوری":
            delete_reminder(chat_id)
            await update.message.reply_text(
                "✅ یادآوری شما حذف شد.",
                reply_markup=main_menu()
            )
        else:
            await update.message.reply_text(
                "❌ دستور نامعتبر است. لطفاً از منو استفاده کنید.",
                reply_markup=main_menu()
            )
            
    except Exception as e:
        logger.error(f"Error handling message from {update.effective_chat.id}: {e}")
        await update.message.reply_text(
            "❌ خطایی در پردازش درخواست شما رخ داد. لطفاً دوباره تلاش کنید."
        )

def main():
    # ایجاد برنامه
    application = Application.builder().token(TOKEN).build()

    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ایجاد و شروع scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: application.create_task(send_reminders(application)),
        'interval', 
        minutes=1
    )
    scheduler.start()

    # شروع ربات
    logger.info("🤖 Bot started successfully!")
    logger.info(f"🕒 Current Iran time: {get_iran_time()}")
    
    application.run_polling()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
