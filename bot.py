
import os
import logging
import sqlite3
import uuid
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

NAME, SERVICE, DAY, SLOT, CONFIRM = range(5)

SERVICES = ["Haircut", "Hair Styling", "Consultation"]
SLOTS = ["09:00", "10:00", "11:00", "12:00", "14:00", "15:00", "16:00"]
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Africa/Lagos"))
DB_PATH = os.getenv("DB_PATH", "appointments.db")


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                ref TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                service TEXT NOT NULL,
                day TEXT NOT NULL,
                slot TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending',
                created_at TEXT NOT NULL,
                UNIQUE(day, slot)
            )
        """)


def available_slots(day):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT slot FROM appointments WHERE day = ?",
            (day,),
        ).fetchall()
    booked = {row[0] for row in rows}
    return [slot for slot in SLOTS if slot not in booked]


def keyboard(items):
    return ReplyKeyboardMarkup(
        [[item] for item in items],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to Smart Appointment Booking! 👋\n\n"
        "Book an appointment in a few simple steps.\n"
        "Use /book to get started or /help for instructions."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/start - Welcome message\n"
        "/book - Make an appointment request\n"
        "/cancel - Cancel your current booking process\n"
        "/help - Show this help message"
    )


async def book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("What name should we use for your appointment?")
    return NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2 or len(name) > 80:
        await update.message.reply_text("Please enter a name between 2 and 80 characters.")
        return NAME

    context.user_data["name"] = name
    await update.message.reply_text(
        "Choose a service:",
        reply_markup=keyboard(SERVICES),
    )
    return SERVICE


async def get_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    service = update.message.text.strip()
    if service not in SERVICES:
        await update.message.reply_text(
            "Please select one of the listed services.",
            reply_markup=keyboard(SERVICES),
        )
        return SERVICE

    context.user_data["service"] = service
    today = datetime.now(TIMEZONE).date()
    days = [(today.fromordinal(today.toordinal() + i)).isoformat() for i in range(1, 8)]

    await update.message.reply_text(
        "Choose a date (YYYY-MM-DD):\n" + "\n".join(days),
        reply_markup=keyboard(days),
    )
    return DAY


async def get_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    try:
        selected = date.fromisoformat(raw)
    except ValueError:
        await update.message.reply_text("Use the date format YYYY-MM-DD.")
        return DAY

    today = datetime.now(TIMEZONE).date()
    if selected <= today or (selected - today).days > 7:
        days = [(today.fromordinal(today.toordinal() + i)).isoformat() for i in range(1, 8)]
        await update.message.reply_text(
            "Please choose one of these dates:\n" + "\n".join(days),
            reply_markup=keyboard(days),
        )
        return DAY

    context.user_data["day"] = selected.isoformat()
    slots = available_slots(selected.isoformat())
    if not slots:
        await update.message.reply_text(
            "Sorry, that date is fully booked. Please choose another date."
        )
        return DAY

    await update.message.reply_text(
        "Choose an available time:",
        reply_markup=keyboard(slots),
    )
    return SLOT


async def get_slot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    slot = update.message.text.strip()
    day = context.user_data["day"]
    if slot not in available_slots(day):
        await update.message.reply_text(
            "That time is unavailable. Please choose another.",
            reply_markup=keyboard(available_slots(day)),
        )
        return SLOT

    context.user_data["slot"] = slot
    await update.message.reply_text(
        f"Please confirm your appointment:\n\n"
        f"Name: {context.user_data['name']}\n"
        f"Service: {context.user_data['service']}\n"
        f"Date: {day}\n"
        f"Time: {slot} (Lagos time)\n\n"
        "Type YES to submit or NO to cancel."
    )
    return CONFIRM


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.message.text.strip().upper()
    if answer == "NO":
        context.user_data.clear()
        await update.message.reply_text("Booking cancelled. Use /book to try again.")
        return ConversationHandler.END

    if answer != "YES":
        await update.message.reply_text("Please type YES to submit or NO to cancel.")
        return CONFIRM

    ref = uuid.uuid4().hex[:8].upper()
    data = context.user_data
    day, slot = data["day"], data["slot"]

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """INSERT INTO appointments
                (ref, user_id, name, service, day, slot, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    ref,
                    update.effective_user.id,
                    data["name"],
                    data["service"],
                    day,
                    slot,
                    datetime.now(TIMEZONE).isoformat(),
                ),
            )
    except sqlite3.IntegrityError:
        await update.message.reply_text(
            "Sorry, someone just booked that time. Please use /book to choose another."
        )
        context.user_data.clear()
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        f"Your appointment request has been saved! ✅\n\n"
        f"Reference: {ref}\n"
        f"Status: Pending confirmation\n\n"
        "The business will need to confirm your appointment."
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Booking process cancelled.")
    return ConversationHandler.END


def main():
    init_db()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is missing from environment variables.")

    app = Application.builder().token(token).build()
    conversation = ConversationHandler(
        entry_points=[CommandHandler("book", book)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_service)],
            DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_day)],
            SLOT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_slot)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(conversation)
    app.add_handler(CommandHandler("cancel", cancel))
    print("Appointment bot is starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
