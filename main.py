import asyncio
from datetime import datetime, timedelta, timezone
import pytz
import jdatetime
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# --------- تنظیمات اصلی ---------
# پیشنهاد: برای محیط واقعی، این مقدار را از متغیر محیطی بخوان و توکن را rotate کن.
BOT_TOKEN = "8381121739:AAFB2YBMomBh9xhoI3Qn0VVuGaGlpea9fx8"
IR_TZ = pytz.timezone("Asia/Tehran")

# گروه‌ها
GROUPS = {
    "math": "ریاضی",
    "human": "انسانی",
    "exp": "تجربی",
    "art": "هنر",
    "lang": "زبان"
}

# تنها نوبت کنکور ۱۴۰۵ (تیرماه)
ROUNDS = {
    "r1": "کنکور ۱۴۰۵ (تیر)"
}

# --------- برنامه ۱۴۰۵ (قابل ویرایش) ---------
# فرض پیش‌فرض: پنج‌شنبه و جمعه ۱۱ و ۱۲ تیر ۱۴۰۵
# الگو: صبح گروه‌های ریاضی/انسانی/تجربی ساعت ۸:۰۰ — عصر هنر/زبان ساعت ۱۴:۳۰
# در صورت انتشار اطلاعیه جدید، فقط تاریخ/ساعت‌ها را در این دیکشنری اصلاح کن.
SCHEDULE = {
    "r1": {
        # روز اول: 1405/04/11
        "math":  {"jdate": (1405, 4, 11), "hour": 8,  "minute": 0},    # صبح
        "human": {"jdate": (1405, 4, 11), "hour": 8,  "minute": 0},    # صبح
        "art":   {"jdate": (1405, 4, 11), "hour": 14, "minute": 30},   # عصر
        # روز دوم: 1405/04/12
        "exp":   {"jdate": (1405, 4, 12), "hour": 8,  "minute": 0},    # صبح
        "lang":  {"jdate": (1405, 4, 12), "hour": 14, "minute": 30},   # عصر
    }
}

# --------- UI ---------
main_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⏳ زمان باقی‌مانده")],
        [KeyboardButton(text="🎯 انتخاب گروه"), KeyboardButton(text="🔔 روشن کردن یادآور")],
        [KeyboardButton(text="🔕 خاموش کردن یادآور"), KeyboardButton(text="⏰ تعیین ساعت یادآور")]
    ],
    resize_keyboard=True
)

def choose_group_inline():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=GROUPS["math"],  callback_data="group:math"),
         InlineKeyboardButton(text=GROUPS["human"], callback_data="group:human")],
        [InlineKeyboardButton(text=GROUPS["exp"],   callback_data="group:exp")],
        [InlineKeyboardButton(text=GROUPS["art"],   callback_data="group:art"),
         InlineKeyboardButton(text=GROUPS["lang"],  callback_data="group:lang")],
    ])
    return kb

HELP_TEXT = (
    "سلام! من شمارش‌گر معکوس کنکور ۱۴۰۵ هستم.\n"
    "اول گروه آزمایشی‌ت رو انتخاب کن (🎯 انتخاب گروه).\n"
    "بعد می‌تونی زمان باقی‌مانده رو ببینی و یادآور روزانه بذاری.\n"
    "دستورات: /start /help /left /sethour HH /remind_on /remind_off"
)

# --------- DB ---------
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY,
  round TEXT DEFAULT 'r1',
  grp TEXT DEFAULT 'exp',
  remind_enabled INTEGER DEFAULT 0,
  reminder_hour_irt INTEGER DEFAULT 8
);
"""

async def init_db():
    async with aiosqlite.connect("data.db") as db:
        await db.execute(CREATE_SQL)
        await db.commit()

async def get_user(uid: int):
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute("SELECT round, grp, remind_enabled, reminder_hour_irt FROM users WHERE user_id=?", (uid,))
        row = await cur.fetchone()
        if row:
            return {"round": row[0], "grp": row[1], "remind_enabled": bool(row[2]), "hour": row[3]}
        await db.execute("INSERT INTO users(user_id) VALUES(?)", (uid,))
        await db.commit()
        return {"round": "r1", "grp": "exp", "remind_enabled": False, "hour": 8}

async def set_group(uid: int, grp: str):
    async with aiosqlite.connect("data.db") as db:
        await db.execute("UPDATE users SET grp=? WHERE user_id=?", (grp, uid))
        await db.commit()

async def set_reminder(uid: int, enabled: bool):
    async with aiosqlite.connect("data.db") as db:
        await db.execute("UPDATE users SET remind_enabled=? WHERE user_id=?", (1 if enabled else 0, uid))
        await db.commit()

async def set_hour(uid: int, hour: int):
    async with aiosqlite.connect("data.db") as db:
        await db.execute("UPDATE users SET reminder_hour_irt=? WHERE user_id=?", (hour, uid))
        await db.commit()

# --------- زمان‌بندی و محاسبات ---------
def jdate_to_local_dt(jy: int, jm: int, jd: int, hour: int, minute: int):
    gdate = jdatetime.datetime(jy, jm, jd, hour=hour, minute=minute).togregorian()
    local_naive = datetime(gdate.year, gdate.month, gdate.day, hour, minute)
    return IR_TZ.localize(local_naive)

def target_dt_for(user) -> datetime:
    rnd = user.get("round", "r1")
    grp = user.get("grp", "exp")
    info = SCHEDULE[rnd][grp]
    dt_local = jdate_to_local_dt(*info["jdate"], info["hour"], info["minute"])
    return dt_local

def human_left(to_local: datetime) -> str:
    now_local = datetime.now(IR_TZ)
    delta = to_local - now_local
    if delta.total_seconds() <= 0:
        return "به زمان آزمون رسیدی! آروم بمون و بهترینت رو نشون بده 🌟"
    days = delta.days
    hours = (delta.seconds // 3600)
    minutes = (delta.seconds % 3600) // 60
    return f"{days} روز، {hours} ساعت و {minutes} دقیقه"

def fmt_local(dt_local: datetime) -> str:
    j = jdatetime.datetime.fromgregorian(datetime=dt_local)
    return j.strftime("%Y/%m/%d - %H:%M")

# --------- Bot ---------
bot = Bot(BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone=IR_TZ)

@dp.message(Command("start"))
async def start(m: Message):
    user = await get_user(m.from_user.id)
    tgt = target_dt_for(user)
    await m.answer(
        f"خوش اومدی به شمارش‌گر کنکور ۱۴۰۵!\n\n"
        f"{HELP_TEXT}\n\n"
        f"گروه فعلی: {GROUPS[user['grp']]}\n"
        f"تاریخ آزمون: {fmt_local(tgt)}\n"
        f"⏳ زمان باقی‌مانده: {human_left(tgt)}",
        reply_markup=main_kb
    )

@dp.message(Command("help"))
async def help_cmd(m: Message):
    await m.answer(HELP_TEXT, reply_markup=main_kb)

@dp.message(Command("left"))
async def left_cmd(m: Message):
    user = await get_user(m.from_user.id)
    tgt = target_dt_for(user)
    await m.answer(
        f"گروه: {GROUPS[user['grp']]}\n"
        f"تاریخ آزمون: {fmt_local(tgt)}\n"
        f"⏳ باقی‌مانده: {human_left(tgt)}"
    )

@dp.message(F.text == "🎯 انتخاب گروه")
async def choose_group(m: Message):
    await m.answer("گروه آزمایشی‌ت رو انتخاب کن:", reply_markup=choose_group_inline())

@dp.callback_query(F.data.startswith("group:"))
async def pick_group(cq: CallbackQuery):
    grp = cq.data.split(":")[1]
    await set_group(cq.from_user.id, grp)
    user = await get_user(cq.from_user.id)
    tgt = target_dt_for(user)
    await cq.message.edit_text(
        f"گروه {GROUPS[grp]} ثبت شد ✅\n"
        f"تاریخ آزمون: {fmt_local(tgt)}\n"
        f"⏳ باقی‌مانده: {human_left(tgt)}"
    )
    await cq.answer()

@dp.message(F.text == "⏳ زمان باقی‌مانده")
async def kb_left(m: Message):
    await left_cmd(m)

@dp.message(F.text == "🔔 روشن کردن یادآور")
async def kb_on(m: Message):
    await set_reminder(m.from_user.id, True)
    await m.answer("یادآوری روزانه روشن شد. برای تعیین ساعت از «⏰ تعیین ساعت یادآور» استفاده کن.")

@dp.message(F.text == "🔕 خاموش کردن یادآور")
async def kb_off(m: Message):
    await set_reminder(m.from_user.id, False)
    await m.answer("یادآوری روزانه خاموش شد.")

@dp.message(F.text == "⏰ تعیین ساعت یادآور")
async def kb_sethour_hint(m: Message):
    await m.answer("فرمت: /sethour 8  (بین 0 تا 23)")

@dp.message(Command("remind_on"))
async def remind_on_cmd(m: Message):
    await set_reminder(m.from_user.id, True)
    await m.answer("یادآوری روزانه روشن شد.")

@dp.message(Command("remind_off"))
async def remind_off_cmd(m: Message):
    await set_reminder(m.from_user.id, False)
    await m.answer("یادآوری روزانه خاموش شد.")

@dp.message(Command("sethour"))
async def sethour_cmd(m: Message):
    parts = m.text.strip().split()
    if len(parts) != 2 or not parts[1].isdigit():
        await m.answer("فرمت درست: /sethour 8  (0 تا 23)")
        return
    h = int(parts[1])
    if not (0 <= h <= 23):
        await m.answer("ساعت باید بین 0 تا 23 باشد.")
        return
    await set_hour(m.from_user.id, h)
    await m.answer(f"ساعت یادآوری روی {h}:00 به وقت ایران تنظیم شد.")

# --------- Scheduler ---------
async def daily_reminder():
    now_local = datetime.now(IR_TZ)
    hour_now = now_local.hour
    async with aiosqlite.connect("data.db") as db:
        cur = await db.execute(
            "SELECT user_id, round, grp FROM users WHERE remind_enabled=1 AND reminder_hour_irt=?",
            (hour_now,)
        )
        rows = await cur.fetchall()
    for uid, rnd, grp in rows:
        try:
            user = {"round": rnd, "grp": grp}
            tgt = target_dt_for(user)
            txt = (
                f"یادآور روزانه ⏰\n"
                f"گروه: {GROUPS[grp]}\n"
                f"تاریخ آزمون: {fmt_local(tgt)}\n"
                f"⏳ باقی‌مانده: {human_left(tgt)}"
            )
            await bot.send_message(uid, txt)
        except Exception:
            pass

async def main():
    if not BOT_TOKEN:
        print("BOT_TOKEN تنظیم نشده.")
        return
    await init_db()
    scheduler.add_job(daily_reminder, CronTrigger(minute="0"))  # هر ساعت در دقیقه ۰
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
