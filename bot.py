"""Telegram bot entry point for the Running Coach.

Usage:
    # First time setup (if not done already):
    python auth.py

    # Run the bot:
    python bot.py
"""
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from anthropic import RateLimitError

from config import get_config
from coach.agent import CoachSession
import db

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Single shared session — one MCP subprocess for the whole bot lifetime
_coach: CoachSession | None = None

# Telegram max message length
_MAX_LEN = 4096

_ALLOWED_USER_ID = int(os.environ.get("TELEGRAM_ALLOWED_USER_ID", 0))


def _split(text: str) -> list[str]:
    """Split a long response into ≤4096-char chunks on newline boundaries."""
    if len(text) <= _MAX_LEN:
        return [text]
    chunks, current = [], []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if current_len + len(line) > _MAX_LEN and current:
            chunks.append("".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line)
    if current:
        chunks.append("".join(current))
    return chunks


def _is_allowed(update: Update) -> bool:
    return update.effective_user.id == _ALLOWED_USER_ID


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    await update.message.reply_text(
        "Running Coach is ready! Ask me anything about your training.\n\n"
        "/reset — clear conversation history\n"
        "/memory — view what I remember about you\n"
        "/clearmemory — wipe my memory"
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    await _coach.clear_history(update.effective_chat.id)
    await update.message.reply_text("Conversation history cleared. Fresh start!")


async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    facts = _coach.get_memory(update.effective_chat.id)
    if not facts:
        await update.message.reply_text(
            "No memory yet. Chat with me and I'll start remembering things about your training."
        )
    else:
        lines = "\n".join(f"• {f}" for f in facts)
        await update.message.reply_text(f"What I remember about you:\n\n{lines}")


async def cmd_clearmemory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    await _coach.clear_memory(update.effective_chat.id)
    await update.message.reply_text("Memory cleared. I've forgotten everything I knew about you.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    chat_id = update.effective_chat.id
    user_message = update.message.text

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        reply = await _coach.chat(chat_id, user_message)
        if reply:
            for chunk in _split(reply):
                await update.message.reply_text(chunk)
        else:
            await update.message.reply_text("I didn't get a response. Please try again.")
    except RateLimitError:
        await update.message.reply_text(
            "I'm being rate limited by the API. Please wait a minute and try again."
        )
    except Exception:
        logger.exception("Error processing message from chat %s", chat_id)
        await update.message.reply_text(
            "Something went wrong on my end. Please try again."
        )


async def post_init(application: Application):
    global _coach
    await db.init_pool()
    logger.info("Starting coach session...")
    _coach = CoachSession()
    await _coach.start()
    logger.info("Coach session ready.")


async def post_shutdown(application: Application):
    if _coach:
        logger.info("Shutting down coach session...")
        await _coach.stop()
    await db.close_pool()


def check_setup():
    try:
        config = get_config()
    except KeyError as e:
        print(f"Missing environment variable: {e}")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    if not config.access_token or not config.refresh_token:
        print("Strava not authenticated yet. Run:  python auth.py")
        sys.exit(1)

    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        print("Missing TELEGRAM_BOT_TOKEN in .env")
        sys.exit(1)

    if not os.environ.get("TELEGRAM_ALLOWED_USER_ID"):
        print("Missing TELEGRAM_ALLOWED_USER_ID in .env")
        sys.exit(1)


def main():
    check_setup()

    app = (
        Application.builder()
        .token(os.environ["TELEGRAM_BOT_TOKEN"])
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("clearmemory", cmd_clearmemory))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
