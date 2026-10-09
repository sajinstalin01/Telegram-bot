# Telegram Social Media Video Downloader

Python Telegram bot built with aiogram, yt-dlp, FFmpeg and PostgreSQL.

## Features
- Video quality selection: up to 720p, up to 480p, or best available
- MP3 audio extraction using FFmpeg
- Download progress updates when source progress is available
- PostgreSQL download history with `/history`
- `/start`, `/help`, and admin `/status`
- URL host allowlist and short-lived, user-bound selections
- Temporary download files and configurable concurrent downloads
- Docker Compose with persistent PostgreSQL storage

## Supported sources
YouTube, Instagram, Facebook, TikTok, Pinterest, X/Twitter, Reddit and ShareChat, depending on current yt-dlp support and source restrictions.

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

## Notes
`MAX_FILE_MB=49` is a conservative cap for standard Telegram cloud Bot API uploads. Some sites may block automated downloads or restrict formats. This bot does not bypass private-post access, login walls, DRM, or other access controls. Download only content you own or are authorized to save.

PostgreSQL stores the Telegram user ID, source host, media type, selected quality, result and timestamp. It does not store source URLs.
