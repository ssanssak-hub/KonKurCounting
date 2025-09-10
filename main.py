# هندل پیام‌ها
def handle_message(chat_id: int, text: str):
    # 1) اگر در حالت وارد کردن ساعت یادآوری هستیم
    if chat_id in user_reminders and user_reminders[chat_id].get("step") == "set_time":
        if text == "⬅️ بازگشت":
            user_reminders[chat_id]["step"] = None
            user_reminders[chat_id]["pending_exam"] = None
            send_message(chat_id, "↩️ بازگشتی به منوی اصلی:", reply_markup=main_menu())
            return
        try:
            reminder_time = text.strip()
            exam_name = user_reminders[chat_id]["pending_exam"]
            logger.info(f"⏱ Raw time input: {repr(reminder_time)}")
            schedule_reminder(chat_id, exam_name, reminder_time)
            user_reminders[chat_id]["step"] = None
            user_reminders[chat_id]["pending_exam"] = None
            send_message(chat_id, f"✅ یادآوری برای کنکور {exam_name} هر روز در ساعت {reminder_time} تنظیم شد.")
        except Exception:
            logger.error(f"reminder error: {traceback.format_exc()}")
            send_message(chat_id, "⚠️ فرمت ساعت درست نیست. لطفاً به صورت 24 ساعته وارد کن (مثال‌ها: 20:00، 07:30).")
        return

    # 2) سایر پیام‌ها
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
        if chat_id not in user_reminders:
            user_reminders[chat_id] = {"reminders": [], "step": None, "pending_exam": None}
        user_reminders[chat_id]["step"] = "choose_exam"
        user_reminders[chat_id]["pending_exam"] = None
        return

    elif text == "❌ مدیریت یادآوری‌ها":
        reminders = user_reminders.get(chat_id, {}).get("reminders", [])
        if not reminders:
            send_message(chat_id, "📭 هیچ یادآوری فعالی نداری.")
        else:
            for r in reminders:
                msg = f"🔔 کنکور {r['exam']} – ساعت {r['time']}"
                inline_kb = [[{"text": "❌ حذف", "callback_data": f"remdel|{r['exam']}"}]]
                send_message_inline(chat_id, msg, inline_kb)
        return

    elif text in ["🧪 کنکور تجربی", "📐 کنکور ریاضی", "📚 کنکور انسانی", "🎨 کنکور هنر", "🏫 کنکور فرهنگیان"]:
        exam_name = text.split()[-1]
        if user_reminders.get(chat_id, {}).get("step") == "choose_exam":
            user_reminders[chat_id]["pending_exam"] = exam_name
            user_reminders[chat_id]["step"] = "set_time"
            send_message(chat_id,
                f"⏰ لطفاً ساعت یادآوری روزانه برای کنکور {exam_name} رو وارد کن.\n"
                f"فرمت باید 24 ساعته باشه (HH:MM).\n\n"
                f"می‌تونی با اعداد فارسی یا انگلیسی هم بنویسی.\n"
                f"مثال‌ها:\n20:00 → ساعت 8 شب\n07:30 → ساعت 7 و نیم صبح"
            )
        else:
            countdown = get_countdown(exam_name)
            send_message(chat_id, countdown)
        return

    elif text == "➕ ثبت مطالعه":
        send_message(
            chat_id,
            "📚 لطفاً اطلاعات مطالعه را به این شکل وارد کنید:\n\n"
            "نام درس، ساعت شروع (hh:mm)، ساعت پایان (hh:mm)، مدت (ساعت)\n\n"
            "مثال:\nریاضی، 14:00، 16:00، 2"
        )
        return

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
            logger.error(f"Study parse error: {traceback.format_exc()}")
            send_message(chat_id, "⚠️ مشکلی در ثبت پیش آمد. دوباره امتحان کن.")
        return
