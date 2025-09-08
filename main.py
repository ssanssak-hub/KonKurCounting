#!/usr/bin/env python3
# coding: utf-8

import os
import json
import sqlite3
import datetime
import logging
from typing import Optional

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:
    ZoneInfo = None

import jdatetime
import requests
from flask import Flask, request, jsonify

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- Config ----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
PUBLIC_URL = os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")

WEBHOOK_PATH = f"/webhook/{WEBHOOK_SECRET}" if WEBHOOK_SECRET else f"/webhook/{BOT_TOKEN}"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = Flask(__name__)

# ---------------- Database ----------------
DB_FILE = "study.db"

def init_db():
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS study_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                subject TEXT,
                start_time TEXT,
                duration REAL,
                date TEXT
            )
        """)
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"DB init failed: {e}")

init_db()

# ---------------- Exams ----------------
EXAMS = {
    "تجربی": (jdatetime.datetime(1405, 4, 12, 8, 0), "08:00 صبح"),
    "ریاضی": (jdatetime.datetime(1405, 4, 11, 8, 0), "08:00 صبح"),
    "انسانی": (jdatetime.datetime(1405, 4, 11, 8, 0), "08:00 صبح"),
    "هنر": (jdatetime.datetime(1405, 4, 12, 14, 30), "14:30 بعدازظهر"),
    "فرهنگیان": (jdatetime.datetime(1405, 2, 17, 8, 0), "08:00 صبح (17 و 18 اردیبهشت)"),
}

ALIASES = {
    "tajrobi": "تجربی",
    "riazi": "ریاضی",
    "ensani": "انسانی",
    "honar": "هنر",
    "farhangi": "فرهنگیان",
}

# ---------------- Utils ----------------
def to_gregorian(jdt: jdatetime.datetime) -> datetime.datetime:
    return jdt.togregorian()

def now_tehran() -> datetime.datetime:
    try:
        if ZoneInfo:
            return datetime.datetime.now(ZoneInfo("Asia/Tehran"))
    except Exception:
        pass
    return datetime.datetime.utcnow()

def days_until(jdt: jdatetime.datetime) -> int:
    try:
        return (to_gregorian(jdt).date() - now_tehran().date()).days
    except Exception as e:
        logger.error(f"days_until error: {e}")
        return -999

def send_message(chat_id: int, text: str, reply_markup: Optional[dict] = None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    try:
        r = requests.post(f"{TELEGRAM_API}/sendMessage", data=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"send_message failed: {e}")

def build_main_keyboard() -> dict:
    keyboard = [
        [{"text": "تجربی"}, {"text": "ریاضی"}],
        [{"text": "انسانی"}, {"text": "هنر"}],
        [{"text": "فرهنگیان"}],
    ]
    return {"keyboard": keyboard, "resize_keyboard": True}

def resolve_exam(text: str) -> Optional[str]:
    t = text.strip().lower()
    if t in EXAMS:
        return t
    if t in ALIASES:
        return ALIASES[t]
    return None

# ---------------- Flask Routes ----------------
@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    try:
        update = request.get_json(force=True, silent=True)
        if not update:
            return jsonify({"ok": False}), 400

        message = update.get("message") or update.get("edited_message")
        if message:
            chat_id = message["chat"]["id"]
            text = message.get("text") or ""
            if text:
                handle_message(chat_id, text, message["from"]["id"])
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return "OK"

def handle_message(chat_id: int, text: str, user_id: int):
    try:
        lower = text.strip().lower()

        if lower.startswith("/start") or lower.startswith("شروع"):
            msg = (
                "سلام 👋\n"
                "من ربات روزشمار و برنامه‌ریز کنکور هستم 📚\n\n"
                "رشته‌ها:\n"
                "• تجربی (12 تیر 1405 ساعت 08:00)\n"
                "• ریاضی (11 تیر 1405 ساعت 08:00)\n"
                "• انسانی (11 تیر 1405 ساعت 08:00)\n"
                "• هنر (12 تیر 1405 ساعت 14:30)\n"
                "• فرهنگیان (17 و 18 اردیبهشت 1405 ساعت 08:00)\n\n"
                "➕ برای ثبت مطالعه: `/add درس ساعتشروع مدت(ساعت)`\n"
                "📊 برای مشاهده پیشرفت: `/progress`"
            )
            send_message(chat_id, msg, reply_markup=build_main_keyboard())
            return

        if lower.startswith("/add"):
            parts = text.split()
            if len(parts) != 4:
                send_message(chat_id, "❌ فرمت دستور اشتباه است.\nمثال: /add ریاضی 08:00 2")
                return
            _, subject, start_time, duration = parts
            try:
                dur = float(duration)
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("INSERT INTO study_log (user_id, subject, start_time, duration, date) VALUES (?, ?, ?, ?, ?)",
                          (user_id, subject, start_time, dur, now_tehran().date().isoformat()))
                conn.commit()
                conn.close()
                send_message(chat_id, f"✅ {dur} ساعت مطالعه برای {subject} ثبت شد.")
            except Exception as e:
                logger.error(f"/add failed: {e}")
                send_message(chat_id, "❌ خطا در ثبت مطالعه.")
            return

        if lower.startswith("/progress"):
            try:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                today = now_tehran().date()
                week_ago = today - datetime.timedelta(days=7)

                c.execute("SELECT SUM(duration) FROM study_log WHERE user_id=? AND date>=?", (user_id, str(week_ago)))
                week_total = c.fetchone()[0] or 0

                c.execute("SELECT SUM(duration) FROM study_log WHERE user_id=? AND date<? AND date>=?", (user_id, str(week_ago), str(week_ago - datetime.timedelta(days=7))))
                prev_total = c.fetchone()[0] or 0

                conn.close()

                diff = week_total - prev_total
                trend = "📈 پیشرفت" if diff > 0 else ("📉 پسرفت" if diff < 0 else "➖ بدون تغییر")
                send_message(chat_id, f"این هفته: {week_total} ساعت\nهفته قبل: {prev_total} ساعت\nوضعیت: {trend}")
            except Exception as e:
                logger.error(f"/progress failed: {e}")
                send_message(chat_id, "❌ خطا در محاسبه پیشرفت.")
            return

        exam = resolve_exam(text)
        if exam:
            jdt, time_text = EXAMS[exam]
            d = days_until(jdt)
            if d >= 1:
                msg = f"⏳ تا کنکور «{exam}» {d} روز مانده.\n🕗 ساعت شروع: {time_text}"
            elif d == 0:
                msg = f"🎯 امروز کنکور «{exam}» برگزار می‌شود!\n🕗 ساعت شروع: {time_text}"
            else:
                msg = f"✅ کنکور «{exam}» برگزار شده است."
            send_message(chat_id, msg)
        else:
            send_message(chat_id, "❌ رشته یا دستور ناشناخته بود.", reply_markup=build_main_keyboard())

    except Exception as e:
        logger.error(f"handle_message error: {e}")
        send_message(chat_id, "❌ خطای داخلی ربات.")

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    if not PUBLIC_URL:
        return jsonify({"ok": False, "error": "PUBLIC_URL not set"}), 400
    url = f"{PUBLIC_URL}{WEBHOOK_PATH}"
    try:
        r = requests.post(f"{TELEGRAM_API}/setWebhook", data={"url": url}, timeout=10)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
