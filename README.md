# Telegram Social Media Video Downloader

Python Telegram bot built with aiogram, yt-dlp, FFmpeg and PostgreSQL.

## Features
- Automatic platform detection from links (including links pasted with surrounding text)
- Supported sources: YouTube, Instagram, Facebook, TikTok, Pinterest, X/Twitter, Reddit and ShareChat, subject to current yt-dlp support and site restrictions
- Quality picker with **Best available** as the default option, plus 720p, 480p and MP3 audio at 192 kbps
- Saves files using the source media title when the platform provides one, rather than a generic filename
- Download progress updates when source progress is available
- PostgreSQL download history with `/history`
- Admin manager: `/admin`, statistics, recent activity, admin list, `/admin_add USER_ID`, `/admin_remove USER_ID`
- `/start`, `/help`, and admin `/status`
- URL host allowlist and short-lived, user-bound quality selections
- Temporary download files and configurable concurrent downloads
- Docker Compose with persistent PostgreSQL storage

## Setup
1. Create a Telegram bot with `@BotFather`.
2. Copy `.env.example` to `.env` and configure `BOT_TOKEN`, `ADMIN_IDS`, `DATABASE_URL`, and a strong `POSTGRES_PASSWORD`.
3. Install Python 3.11+, FFmpeg and PostgreSQL for a local run.
4. Install dependencies with `pip install -r requirements.txt`.
5. Run `python bot.py`.

## Docker
With Docker Compose installed, run:

```bash
docker compose up --build -d
docker compose logs -f bot
```

Ensure the password in `DATABASE_URL` matches `POSTGRES_PASSWORD`. For local PostgreSQL, use `localhost` rather than `db` as the database host.

## Admin manager
- Put one or more Telegram numeric user IDs in `ADMIN_IDS`, separated by commas. At least one initial admin is strongly recommended.
- `/admin` opens the admin panel.
- `/admin_stats` shows total, successful and failed attempts, active users and admin count.
- `/admin_recent` shows the latest download attempts.
- `/admin_add USER_ID` and `/admin_remove USER_ID` manage database-backed admins. The IDs configured in `ADMIN_IDS` are protected from removal in the bot; remove them from `.env` if you need to revoke them.
- Dynamic admin management and statistics require PostgreSQL.

## Notes
`MAX_FILE_MB=49` is a conservative cap for standard Telegram cloud Bot API uploads. Some sites may block automated downloads or restrict formats. This bot does not bypass private-post access, login walls, DRM, or other access controls. Download only content you own or are authorized to save.

PostgreSQL stores the Telegram user ID, source host, media type, selected quality, result and timestamp. It does not store source URLs. Keep `.env` private and never commit your real bot token or database password.
