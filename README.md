# Telegram Social Media Video Downloader

Python Telegram bot using aiogram, yt-dlp, FFmpeg, SQLite for local use, and PostgreSQL in Docker.

## Features
- Automatically detects supported platform links: YouTube, Instagram, Facebook, TikTok, Pinterest, X/Twitter, Reddit and ShareChat (subject to current yt-dlp support and site restrictions).
- Quality picker: Best available (default), 720p, 480p, or MP3 audio at 192 kbps.
- Saves downloads using the source media title when available.
- Progress updates, temporary download files, and configurable concurrent downloads.
- Download history: `/history`.
- Admin panel: `/admin`, `/admin_stats`, `/admin_recent`.
- Owner-only admin management: `/admin_add USER_ID` and `/admin_remove USER_ID`.
- SQLite database by default for Windows/local runs; PostgreSQL remains enabled for Docker deployment.
- URL host allowlist and user-bound short-lived quality selections.

## Local Windows setup
1. Create a Telegram bot with `@BotFather`.
2. Copy `.env.example` to `.env`.
3. Set `BOT_TOKEN`, and set your numeric Telegram ID in both `OWNER_IDS` and `ADMIN_IDS`.
4. Keep `DATABASE_URL=sqlite:///telegram_bot.db` and `DATABASE_PATH=telegram_bot.db` for local use. SQLite is built into Python; no database server or PostgreSQL installation is required.
5. Install Python 3.11+, FFmpeg, and dependencies:
   ```powershell
   pip install -r requirements.txt
   python bot.py
   ```

The SQLite file is created automatically next to the project. Keep it private; it stores download history and dynamically added admins.

## Docker / PostgreSQL
Docker Compose overrides `DATABASE_URL` to connect to the included PostgreSQL service. Set a strong `POSTGRES_PASSWORD` in `.env`, then run:
```bash
docker compose up --build -d
docker compose logs -f bot
```
The database data persists in the `postgres_data` volume.

If a configured PostgreSQL connection fails during local execution, the bot logs a warning and falls back to SQLite at `DATABASE_PATH`, avoiding a DNS error from the Docker-only hostname `db`.

## Admin manager
- `OWNER_IDS`: trusted owner ID(s), separated by commas. Only owners can add or remove admins.
- `ADMIN_IDS`: initial/static admin ID(s), separated by commas. IDs configured here are protected from removal through chat commands; remove them from `.env` to revoke their access.
- `/admin_add USER_ID`: owner-only; adds a database-backed admin.
- `/admin_remove USER_ID`: owner-only; removes a database-backed admin.
- `/admin_stats` and `/admin_recent`: admin statistics and recent activity.
- If `OWNER_IDS` is empty, the bot falls back to `ADMIN_IDS` for backward compatibility. Set `OWNER_IDS` explicitly to keep owner powers separate from regular admins.

## Notes
The upload cap defaults to 49 MB for standard Telegram cloud Bot API uploads. Some platforms may block automated downloads or restrict formats. The bot does not bypass private-post access, login walls, DRM, or other access controls. Download only content you own or are authorized to save. Never commit your real `.env`, bot token, or database password.
