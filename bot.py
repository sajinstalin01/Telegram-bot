import asyncio
import logging
import os
import re
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
DEFAULT_QUALITY = os.getenv("DEFAULT_QUALITY", "best").strip().lower()
if DEFAULT_QUALITY not in {"best", "720", "480"}:
    DEFAULT_QUALITY = "best"
ADMIN_IDS = {
    int(value.strip())
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
}
# Only these owner IDs can grant admin access. Keep OWNER_IDS limited to trusted owners.
OWNER_IDS = {
    int(value.strip())
    for value in os.getenv("OWNER_IDS", "").split(",")
    if value.strip().isdigit()
}
if not OWNER_IDS:
    # Backward-compatible fallback; configure OWNER_IDS explicitly for clear separation.
    OWNER_IDS = set(ADMIN_IDS)
ALLOWED_HOSTS = {
    "youtube.com", "youtu.be", "youtube-nocookie.com",
    "instagram.com", "facebook.com", "fb.watch",
    "tiktok.com", "pinterest.com", "pin.it", "x.com", "twitter.com",
    "reddit.com", "redd.it", "sharechat.com",
}
PLATFORMS = {
    "youtube.com": "YouTube", "youtu.be": "YouTube",
    "youtube-nocookie.com": "YouTube",
    "instagram.com": "Instagram", "facebook.com": "Facebook",
    "fb.watch": "Facebook", "tiktok.com": "TikTok",
    "pinterest.com": "Pinterest", "pin.it": "Pinterest",
    "x.com": "X / Twitter", "twitter.com": "X / Twitter",
    "reddit.com": "Reddit", "redd.it": "Reddit",
    "sharechat.com": "ShareChat",
}
URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
dp = Dispatcher()
db_pool = None
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
pending = {}


def extract_url(text):
    match = URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(".,!?;:)]}>'\"")


def platform_for_url(raw):
    try:
        host = (urlparse(raw.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    for domain, name in PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def valid_url(raw):
    try:
        parsed = urlparse(raw.strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        return (
            parsed.scheme in {"http", "https"}
            and any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_HOSTS)
            and platform_for_url(raw) is not None
        )
    except ValueError:
        return False


async def is_owner(user_id):
    return user_id in OWNER_IDS


async def is_admin(user_id):
    if user_id in OWNER_IDS or user_id in ADMIN_IDS:
        return True
    if db_pool is None:
        return False
    try:
        async with db_pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM bot_admins WHERE user_id = $1)", user_id
            )
    except Exception:
        logging.exception("Could not check admin membership")
        return False


async def db_init():
    global db_pool
    if not DATABASE_URL:
        logging.warning("DATABASE_URL is unset; history and persistent admin management are unavailable.")
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id BIGINT PRIMARY KEY,
                added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                added_by BIGINT
            )
        """)
        for admin_id in ADMIN_IDS:
            await conn.execute(
                "INSERT INTO bot_admins (user_id, added_by) VALUES ($1, $1) ON CONFLICT (user_id) DO NOTHING",
                admin_id,
            )


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
    best_label = "⭐ Best available (default)" if DEFAULT_QUALITY == "best" else "🎬 Best available"
    kb.button(text=best_label, callback_data=f"dl:best:{token}")
    kb.button(text="🎬 720p", callback_data=f"dl:720:{token}")
    kb.button(text="🎬 480p", callback_data=f"dl:480:{token}")
    kb.button(text="🎵 MP3 audio", callback_data=f"dl:mp3:{token}")
    kb.adjust(1, 2, 1)
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
        # yt-dlp uses the source title as the filename instead of a generic media.* name.
        "outtmpl": str(Path(folder) / "%(title).180B.%(ext)s"),
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


def admin_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Statistics", callback_data="admin:stats")
    kb.button(text="🕘 Recent downloads", callback_data="admin:recent")
    kb.button(text="👮 Admin list", callback_data="admin:list")
    kb.adjust(1)
    return kb.as_markup()


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "👋 Welcome to Social Video Downloader!\n\n"
        "Send a public video link from a supported platform. I detect the platform automatically, "
        "then let you choose quality. Best available is the default choice.\n\n"
        "Video: Best / 720p / 480p · Audio: MP3 192 kbps\n"
        "Commands: /help, /history, /status"
        + ("\nAdmin: /admin" if message.from_user and await is_admin(message.from_user.id) else "")
        + "\nOnly download content you own or are authorized to save."
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        "Send a supported public link. The platform is detected automatically.\n"
        "Choose ⭐ Best available (default), 720p, 480p, or MP3 audio.\n"
        "Files are named using the source media title when the platform provides it."
    )


@dp.message(Command("status"))
async def status(message: Message):
    if message.from_user and await is_admin(message.from_user.id):
        db_state = "connected" if db_pool is not None else "not configured"
        await message.answer(
            f"Bot running\nPostgreSQL: {db_state}\nUpload cap: {MAX_FILE_MB} MB\n"
            f"Concurrent downloads: {MAX_CONCURRENT_DOWNLOADS}\nDefault quality: {DEFAULT_QUALITY}"
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


@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not message.from_user or not await is_admin(message.from_user.id):
        await message.answer("⛔ Admin only.")
        return
    await message.answer(
        "🛠 Admin Manager\n\n"
        "Use the buttons for bot statistics, recent download activity and the admin list.\n"
        "Commands:\n/admin_add USER_ID — owner-only: grant admin access\n"
        "/admin_stats — download statistics\n/admin_recent — recent activity\n"
        "Only the configured owner can grant new admin access; admins cannot promote others.",
        reply_markup=admin_keyboard(),
    )


@dp.message(Command("admin_stats"))
async def admin_stats(message: Message):
    if not message.from_user or not await is_admin(message.from_user.id):
        await message.answer("⛔ Admin only.")
        return
    if db_pool is None:
        await message.answer("Configure DATABASE_URL to use persistent statistics.")
        return
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM download_history")
        success = await conn.fetchval("SELECT COUNT(*) FROM download_history WHERE status = 'success'")
        failed = await conn.fetchval("SELECT COUNT(*) FROM download_history WHERE status = 'failed'")
        users = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM download_history")
        admins = await conn.fetchval("SELECT COUNT(*) FROM bot_admins")
    await message.answer(
        f"📊 Bot statistics\nDownload attempts: {total}\nSuccessful: {success}\n"
        f"Failed: {failed}\nUsers with activity: {users}\nAdmins: {admins}"
    )


@dp.message(Command("admin_recent"))
async def admin_recent(message: Message):
    if not message.from_user or not await is_admin(message.from_user.id):
        await message.answer("⛔ Admin only.")
        return
    if db_pool is None:
        await message.answer("Configure DATABASE_URL to view recent activity.")
        return
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_id, source_host, media_type, quality, status, created_at
            FROM download_history ORDER BY created_at DESC LIMIT 10
        """)
    if not rows:
        await message.answer("No download activity yet.")
        return
    lines = ["🕘 Latest download attempts:"]
    for row in rows:
        lines.append(
            f"User {row['user_id']} · {row['source_host']} · {row['media_type']} "
            f"· {row['quality']} · {row['status']}"
        )
    await message.answer("\n".join(lines))


@dp.message(Command("admin_add"))
async def admin_add(message: Message):
    if not message.from_user or not await is_owner(message.from_user.id):
        await message.answer("⛔ Owner only. Only the configured bot owner can grant admin access.")
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /admin_add USER_ID")
        return
    target_id = int(parts[1])
    if db_pool is None:
        await message.answer("Configure DATABASE_URL first; dynamic admin changes must be stored persistently.")
        return
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO bot_admins (user_id, added_by) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING",
            target_id, message.from_user.id,
        )
    await message.answer(f"✅ Admin {target_id} added (or was already an admin).")


@dp.message(Command("admin_remove"))
async def admin_remove(message: Message):
    await message.answer(
        "Admin removal is disabled in chat. Only the configured owner can grant admin access "
        "with /admin_add USER_ID. To revoke access, remove the user from the bot_admins table "
        "in PostgreSQL or remove them from ADMIN_IDS in your .env file."
    )


@dp.callback_query(F.data.startswith("admin:"))
async def admin_button(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Admin only.", show_alert=True)
        return
    await callback.answer()
    action = callback.data.split(":", 1)[1]
    if action == "stats":
        if db_pool is None:
            await callback.message.answer("Configure DATABASE_URL to use persistent statistics.")
            return
        async with db_pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM download_history")
            success = await conn.fetchval("SELECT COUNT(*) FROM download_history WHERE status = 'success'")
            failed = await conn.fetchval("SELECT COUNT(*) FROM download_history WHERE status = 'failed'")
            users = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM download_history")
            admins = await conn.fetchval("SELECT COUNT(*) FROM bot_admins")
        await callback.message.answer(
            f"📊 Bot statistics\nAttempts: {total} · Successful: {success} · Failed: {failed}\n"
            f"Users with activity: {users} · Admins: {admins}"
        )
    elif action == "recent":
        if db_pool is None:
            await callback.message.answer("Configure DATABASE_URL to view recent activity.")
            return
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT user_id, source_host, media_type, quality, status
                FROM download_history ORDER BY created_at DESC LIMIT 10
            """)
        await callback.message.answer(
            "🕘 Recent activity:\n" + ("\n".join(
                f"{r['user_id']} · {r['source_host']} · {r['media_type']} · {r['quality']} · {r['status']}"
                for r in rows
            ) if rows else "No activity yet.")
        )
    elif action == "list":
        if db_pool is None:
            await callback.message.answer("Configured admin IDs: " + (", ".join(map(str, sorted(ADMIN_IDS))) or "none"))
            return
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT user_id FROM bot_admins ORDER BY user_id")
        await callback.message.answer("👮 Admin IDs:\n" + ("\n".join(str(r["user_id"]) for r in rows) or "No admins configured."))


@dp.message(F.text)
async def receive_link(message: Message):
    url = extract_url(message.text or "")
    if not url or not valid_url(url):
        await message.answer("Please send a public URL from YouTube, Instagram, Facebook, TikTok, Pinterest, X/Twitter, Reddit or ShareChat.")
        return
    now = asyncio.get_running_loop().time()
    for key in list(pending):
        if now - pending[key]["created"] > 900:
            pending.pop(key, None)
    token = uuid.uuid4().hex[:12]
    platform = platform_for_url(url)
    pending[token] = {
        "url": url,
        "user_id": message.from_user.id,
        "created": now,
        "platform": platform,
    }
    await message.answer(
        f"🔎 Detected platform: {platform}\nChoose output quality:",
        reply_markup=quality_keyboard(token),
    )


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
    if quality not in {"best", "720", "480", "mp3"}:
        await callback.answer("Invalid quality.", show_alert=True)
        return
    pending.pop(token, None)
    await callback.answer("Starting download…")
    status_message = await callback.message.answer("⏳ Starting…")
    url = job["url"]
    host = (urlparse(url).hostname or "unknown").lower()
    platform = job.get("platform") or platform_for_url(url) or "Unknown platform"
    mode = "mp3" if quality == "mp3" else "video"
    loop = asyncio.get_running_loop()

    async with download_semaphore:
        with tempfile.TemporaryDirectory(prefix="social_dl_") as folder:
            try:
                hook = progress_hook(loop, status_message)
                await asyncio.to_thread(download_sync, url, mode, quality, folder, hook)
                candidates = [
                    path for path in Path(folder).iterdir()
                    if path.is_file() and not path.name.endswith((".part", ".ytdl", ".json"))
                ]
                if not candidates:
                    raise RuntimeError("No output file was created.")
                media = max(candidates, key=lambda path: path.stat().st_size)
                if media.stat().st_size > MAX_FILE_MB * 1024 * 1024:
                    raise ValueError(f"File exceeds the {MAX_FILE_MB} MB limit.")
                await status_message.edit_text("📤 Uploading to Telegram…")
                await bot.send_document(
                    chat_id=callback.message.chat.id,
                    document=FSInputFile(media, filename=media.name),
                    caption=f"✅ {platform} · {mode.upper()} · {quality}\n📁 {media.name}",
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
        logging.exception("PostgreSQL initialization failed; history and persistent admin management are disabled.")
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
