"""Telegram bot for running @jexor_studio: drafts, approvals, ideas, reply drafts.

Nothing reaches X until Alexandra taps a publish button. Replies under other people's posts
are only drafted here; she posts them by hand (no automated likes, follows or replies).
"""

import asyncio
import datetime as dt
import json
import logging
import os
import re
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import brain
import typefully

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("xbot")

OWNER_ID = int(os.environ.get("TELEGRAM_OWNER_ID", "0"))
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Moscow"))
DAILY_TIME = os.environ.get("DAILY_TIME", "09:00")
TOPICS = os.environ.get(
    "TOPICS",
    "affiliate marketing, performance marketing, partner marketing, user acquisition, "
    "growth for startups, gamification and game mechanics in marketing, TON / Telegram apps",
)
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data"))
STATE_FILE = DATA_DIR / "state.json"
INFLUENCERS_FILE = Path(__file__).parent / "influencers.txt"
TWEET_LINK = re.compile(r"https?://(www\.)?(x|twitter)\.com/\S+/status/\d+")

# ---------- state: pending drafts survive restarts ----------

def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"drafts": {}, "editing": None}


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1))


STATE = load_state()


def is_owner(update: Update) -> bool:
    return OWNER_ID and update.effective_user and update.effective_user.id == OWNER_ID


def draft_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Опубликовать сейчас", callback_data=f"now:{draft_id}"),
            InlineKeyboardButton("🕒 В очередь", callback_data=f"queue:{draft_id}"),
        ],
        [
            InlineKeyboardButton("✏️ Править", callback_data=f"edit:{draft_id}"),
            InlineKeyboardButton("📝 В Typefully черновиком", callback_data=f"save:{draft_id}"),
            InlineKeyboardButton("🗑", callback_data=f"del:{draft_id}"),
        ],
    ])


async def send_draft(bot, chat_id: int, text: str) -> None:
    draft_id = uuid.uuid4().hex[:8]
    STATE["drafts"][draft_id] = text
    save_state(STATE)
    await bot.send_message(chat_id, text[:4000], reply_markup=draft_keyboard(draft_id))


async def think(fn, *args) -> str:
    """Run a blocking Claude call without freezing the bot."""
    return await asyncio.to_thread(fn, *args)

# ---------- commands ----------

HELP = (
    "Что я умею:\n"
    "• Напиши мне идею (можно по-русски) — пришлю готовый пост на английском с кнопками.\n"
    "• Пришли ссылку на чужой твит или его текст через /reply — дам 3 варианта ответа, "
    "ты постишь вручную.\n"
    "• /ideas — найду свежие темы в сети и напишу посты под них.\n"
    f"• Каждый день в {DAILY_TIME} сама пришлю идеи и список, под кем ответить.\n"
    "• Голосовые: продиктуй текст через микрофон на клавиатуре телефона и отправь текстом."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update):
        await update.message.reply_text(
            f"Твой Telegram ID: {update.effective_user.id}\n"
            "Впиши его в TELEGRAM_OWNER_ID в настройках сервера и перезапусти бота."
        )
        return
    await update.message.reply_text("Привет! Я твой агент для X.\n\n" + HELP)


async def ideas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update):
        return
    await update.message.reply_text("Ищу свежие темы, это займет минуту-две…")
    await send_ideas(context.bot, update.effective_chat.id)


async def send_ideas(bot, chat_id: int) -> None:
    result = await think(brain.daily_ideas, TOPICS)
    for block in [b.strip() for b in result.split("\n---\n") if b.strip()]:
        if "POST:" in block:
            head, post = block.split("POST:", 1)
            await bot.send_message(chat_id, head.strip()[:4000], disable_web_page_preview=True)
            await send_draft(bot, chat_id, post.strip())
        else:
            await bot.send_message(chat_id, block[:4000], disable_web_page_preview=True)


async def reply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update):
        return
    tweet = " ".join(context.args)
    if not tweet:
        await update.message.reply_text("Пришли так: /reply <ссылка или текст поста>")
        return
    await make_replies(update, tweet)


async def make_replies(update: Update, tweet: str) -> None:
    await update.message.reply_text("Пишу варианты ответа…")
    replies = await think(brain.draft_replies, tweet)
    await update.message.reply_text(
        replies[:4000] + "\n\nСкопируй понравившийся и запости сама под твитом.",
        disable_web_page_preview=True,
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update):
        return
    text = update.message.text.strip()

    editing = STATE.get("editing")
    if editing and editing in STATE["drafts"]:
        STATE["editing"] = None
        save_state(STATE)
        await update.message.reply_text("Переписываю…")
        new = await think(brain.rewrite_post, STATE["drafts"].pop(editing), text)
        await send_draft(context.bot, update.effective_chat.id, new)
        return

    if TWEET_LINK.search(text):
        await make_replies(update, text)
        return

    await update.message.reply_text("Пишу пост…")
    post = await think(brain.draft_post, text)
    await send_draft(context.bot, update.effective_chat.id, post)


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update):
        return
    await update.message.reply_text(
        "Голосовые я пока не расшифровываю. Нажми микрофон на клавиатуре телефона, "
        "продиктуй и отправь текстом — сделаю пост."
    )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_owner(update):
        await query.answer()
        return
    action, draft_id = query.data.split(":", 1)
    text = STATE["drafts"].get(draft_id)
    if text is None:
        await query.answer("Этот черновик уже обработан")
        return

    if action == "edit":
        STATE["editing"] = draft_id
        save_state(STATE)
        await query.answer()
        await query.message.reply_text("Что поменять? Напиши одним сообщением.")
        return

    if action == "del":
        STATE["drafts"].pop(draft_id)
        save_state(STATE)
        await query.answer("Удалено")
        await query.edit_message_reply_markup(None)
        return

    publish_at = {"now": "now", "queue": "next-free-slot", "save": None}[action]
    await query.answer("Отправляю в Typefully…")
    try:
        await asyncio.to_thread(typefully.create_x_draft, text, publish_at)
    except Exception as e:  # show the error to her instead of failing silently
        log.exception("Typefully error")
        await query.message.reply_text(f"Typefully вернул ошибку: {e}")
        return
    STATE["drafts"].pop(draft_id)
    save_state(STATE)
    status = {
        "now": "✅ Опубликовано",
        "queue": "🕒 Поставлено в очередь Typefully",
        "save": "📝 Сохранено черновиком в Typefully",
    }[action]
    await query.edit_message_text(f"{text}\n\n{status}")

# ---------- daily routine ----------

async def daily(context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(OWNER_ID, "Доброе утро! Свежие идеи на сегодня 👇")
    await send_ideas(context.bot, OWNER_ID)
    if INFLUENCERS_FILE.exists():
        handles = [h.strip() for h in INFLUENCERS_FILE.read_text().splitlines()
                   if h.strip() and not h.startswith("#")]
        links = "\n".join(f"https://x.com/{h.lstrip('@')}" for h in handles)
        await context.bot.send_message(
            OWNER_ID,
            "Под кем ответить сегодня (10–15 ответов за день, не больше одного на автора). "
            "Открой, найди свежий пост и скинь мне ссылку — напишу ответ:\n\n" + links,
            disable_web_page_preview=True,
        )


def main() -> None:
    app = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("ideas", ideas))
    app.add_handler(CommandHandler("reply", reply_cmd))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    if OWNER_ID:
        hour, minute = map(int, DAILY_TIME.split(":"))
        app.job_queue.run_daily(daily, dt.time(hour, minute, tzinfo=TZ))

    log.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
