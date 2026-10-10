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

## Automatic GitHub updates

The GitHub Actions workflow at `.github/workflows/validate-and-deploy.yml` runs on every push to `main` and on pull requests. It installs dependencies, checks every Python file for syntax errors, and builds the Docker image. This helps catch problems before deployment.

### Optional automatic Railway deployment
To have every successful push to `main` deploy the latest code to Railway, configure these in **GitHub → Settings → Secrets and variables → Actions**:
- Repository secret `RAILWAY_TOKEN`: a Railway project/environment token with deployment access.
- Repository variable `RAILWAY_DEPLOY_ENABLED`: set to `true`.
- Repository variable `RAILWAY_SERVICE_NAME`: the exact Railway service name for this bot.

The deployment job runs only after validation passes. Leave `RAILWAY_DEPLOY_ENABLED` unset or set it to anything other than `true` to disable automatic Railway deployment. Do not put tokens in source files or commit them.

This workflow does not automatically push edits from your Windows computer to GitHub. To publish local changes, commit and push them with Git; the workflow then validates them and (if configured) deploys them.

### Automatically push changes from your Windows PC
To automatically commit and push edits you make in the local project folder:
1. Pull the latest `main` branch from GitHub and open PowerShell in the repository folder.
2. Make sure Git is installed, `origin` points to this repository, and GitHub authentication is configured. Configure `git config --global user.name "Your Name"` and `git config --global user.email "you@example.com"` if needed.
3. Review `.gitignore` and ensure you have not placed secrets in files that Git tracks. The script skips ignored files such as `.env` and local database files.
4. Run `Set-ExecutionPolicy -Scope Process Bypass` if PowerShell blocks the script, then run `.\auto-push.ps1`.
5. Leave the PowerShell window open. It checks for changes every 5 seconds, commits them, and pushes commits to `origin/main`. Press `Ctrl+C` to stop it.

**Security note:** Automatic commits publish all non-ignored changes in the repository. Review the files and `.gitignore` first, and never store tokens, passwords, or private data in tracked files. The script expects the `main` branch and will not merge remote conflicts automatically.

### Bash and Python auto-push alternatives
The same local watcher is also available in two formats:
- **Bash (Linux/macOS/WSL):** `chmod +x auto-push.sh && ./auto-push.sh`
- **Python (Windows/Linux/macOS):** `python auto_push.py` (requires Python 3 and Git installed)

Both scripts check for local changes every 5 seconds by default, commit them, fetch `origin/main`, and push local commits when the local branch is not behind the remote. If GitHub has new commits that are not in the local branch, the scripts stop rather than overwrite remote history; pull/reconcile manually and restart. You can pass a polling interval in seconds, e.g. `python auto_push.py 10` or `./auto-push.sh 10`.

Use only one watcher for a repository at a time. These scripts publish every non-ignored change in the working tree, so inspect `.gitignore` and never commit credentials or private data. Configure Git identity and GitHub authentication before running.
