import asyncio
import logging
import os
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
from yt_dlp import YoutubeDL

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "49"))
MAX_CONCURRENT_DOWNLOADS = max(1, int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2")))
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
ALLOWED_HOSTS = {
    "youtube.com", "youtu.be", "instagram.com", "facebook.com", "fb.watch",
    "tiktok.com", "pinterest.com", "pin.it", "x.com", "twitter.com",
    "reddit.com", "sharechat.com",
}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
dp = Dispatcher()
db_pool = None
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
pending = {}


def valid_url(raw):
    try:
        parsed = urlparse(raw.strip())
        host = (parsed.hostname or "").lower()
        return parsed.scheme in {"http", "https"} and any(
            host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_HOSTS
        )
    except ValueError:
        return False


async def db_init():
    global db_pool
    if not DATABASE_URL:
        logging.warning("DATABASE_URL is unset; history is unavailable.")
        return
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS download_history (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                source_host TEXT NOT NULL,
                media_type TEXT NOT NULL,
                quality TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_download_history_user_created
            ON download_history (user_id, created_at DESC)
        """)


async def save_history(user_id, host, mode, quality, status):
    if db_pool is None:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO download_history
                   (user_id, source_host, media_type, quality, status)
                   VALUES ($1, $2, $3, $4, $5)""",
                user_id, host, mode, quality, status
            )
    except Exception:
        logging.exception("Could not save download history")


def quality_keyboard(token):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎬 720p", callback_data=f"dl:720:{token}")
    kb.button(text="🎬 480p", callback_data=f"dl:480:{token}")
    kb.button(text="🎬 Best available", callback_data=f"dl:best:{token}")
    kb.button(text="🎵 MP3 audio", callback_data=f"dl:mp3:{token}")
    kb.adjust(2, 2)
    return kb.as_markup()


async def safe_edit(message, text):
    try:
        await message.edit_text(text)
    except Exception:
        pass


def progress_hook(loop, status_message):
    last = {"time": 0.0, "text": ""}

    def hook(data):
        if data.get("status") != "downloading":
            return
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        downloaded = data.get("downloaded_bytes", 0)
        text = f"⬇️ Downloading: {downloaded * 100 / total:.0f}%" if total else "⬇️ Downloading…"
        now = loop.time()
        if text == last["text"] or now - last["time"] < 2:
            return
        last.update(time=now, text=text)
        asyncio.run_coroutine_threadsafe(safe_edit(status_message, text), loop)

    return hook


def download_sync(url, mode, quality, folder, hook):
    options = {
        "outtmpl": str(Path(folder) / "media.%(ext)s"),
        "noplaylist": True,
        "socket_timeout": 25,
        "retries": 2,
        "fragment_retries": 2,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_FILE_MB * 1024 * 1024,
        "progress_hooks": [hook],
    }
    if mode == "mp3":
        options.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    else:
        if quality == "720":
            options["format"] = "bestvideo[height<=720]+bestaudio/best[height<=720]"
        elif quality == "480":
            options["format"] = "bestvideo[height<=480]+bestaudio/best[height<=480]"
        else:
            options["format"] = "bestvideo+bestaudio/best"
        options["merge_output_format"] = "mp4"
    with YoutubeDL(options) as ydl:
        ydl.download([url])


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Welcome to Social Video Downloader!\n\n"
        "Send a public video link, then choose quality or MP3.\n"
        "Supported sources include YouTube, Instagram, Facebook, TikTok, Pinterest, "
        "X/Twitter, Reddit and ShareChat, depending on current site support.\n\n"
        "Commands: /help, /history, /status\n"
        "Only download content you own or are authorized to save."
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer("Send a supported public URL. Choose 720p, 480p, best available, or MP3.")


@dp.message(Command("status"))
async def status(message: Message):
    if message.from_user and message.from_user.id in ADMIN_IDS:
        db_state = "connected" if db_pool is not None else "not configured"
        await message.answer(
            f"Bot running\nPostgreSQL: {db_state}\nUpload cap: {MAX_FILE_MB} MB\n"
            f"Concurrent downloads: {MAX_CONCURRENT_DOWNLOADS}"
        )
    else:
        await message.answer("Bot is online.")


@dp.message(Command("history"))
async def history(message: Message):
    if db_pool is None:
        await message.answer("History is unavailable. Configure DATABASE_URL first.")
        return
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT source_host, media_type, quality, status, created_at
            FROM download_history WHERE user_id = $1
            ORDER BY created_at DESC LIMIT 10
        """, message.from_user.id)
    if not rows:
        await message.answer("No download history found.")
        return
    lines = ["Your latest download attempts:"]
    for row in rows:
        lines.append(f"{row['source_host']} | {row['media_type']} | {row['quality']} | {row['status']}")
    await message.answer("\n".join(lines))


@dp.message(F.text)
async def receive_link(message: Message):
    url = (message.text or "").strip()
    if not valid_url(url):
        await message.answer("Please send a valid public URL from a supported platform.")
        return
    now = asyncio.get_running_loop().time()
    for key in list(pending):
        if now - pending[key]["created"] > 900:
            pending.pop(key, None)
    token = uuid.uuid4().hex[:12]
    pending[token] = {"url": url, "user_id": message.from_user.id, "created": now}
    await message.answer("Choose output:", reply_markup=quality_keyboard(token))


@dp.callback_query(F.data.startswith("dl:"))
async def handle_download(callback: CallbackQuery, bot: Bot):
    try:
        _, quality, token = callback.data.split(":", 2)
    except (ValueError, AttributeError):
        await callback.answer("Invalid selection.", show_alert=True)
        return
    job = pending.get(token)
    if not job or job["user_id"] != callback.from_user.id:
        await callback.answer("Selection expired. Send the link again.", show_alert=True)
        return
    pending.pop(token, None)
    await callback.answer("Starting download…")
    status_message = await callback.message.answer("⏳ Starting…")
    url = job["url"]
    host = (urlparse(url).hostname or "unknown").lower()
    mode = "mp3" if quality == "mp3" else "video"
    loop = asyncio.get_running_loop()

    async with download_semaphore:
        with tempfile.TemporaryDirectory(prefix="social_dl_") as folder:
            try:
                hook = progress_hook(loop, status_message)
                await asyncio.to_thread(download_sync, url, mode, quality, folder, hook)
                candidates = [p for p in Path(folder).glob("media.*") if p.is_file()]
                if not candidates:
                    raise RuntimeError("No output file was created.")
                media = max(candidates, key=lambda p: p.stat().st_size)
                if media.stat().st_size > MAX_FILE_MB * 1024 * 1024:
                    raise ValueError(f"File exceeds the {MAX_FILE_MB} MB limit.")
                await status_message.edit_text("📤 Uploading to Telegram…")
                await bot.send_document(
                    chat_id=callback.message.chat.id,
                    document=FSInputFile(media, filename=media.name),
                    caption=f"✅ {mode.upper()} · {quality}"
                )
                await status_message.delete()
                await save_history(job["user_id"], host, mode, quality, "success")
            except Exception as exc:
                logging.warning("Download failed for %s: %s", host, exc)
                detail = str(exc) if isinstance(exc, ValueError) else (
                    "The post may be private, restricted, unavailable, or unsupported."
                )
                await safe_edit(status_message, f"❌ Download failed. {detail}")
                await save_history(job["user_id"], host, mode, quality, "failed")


async def main():
    global db_pool
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Configure it in .env.")
    try:
        await db_init()
    except Exception:
        logging.exception("PostgreSQL initialization failed; history is disabled.")
        db_pool = None
    bot = Bot(BOT_TOKEN)
    try:
        await dp.start_polling(bot)
    finally:
        if db_pool is not None:
            await db_pool.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
