# 🃏 Pokemon Center Drop Bot — V1 (Pi Edition)

A Raspberry Pi-hosted bot designed to watch PokemonCenter.com for drops
and restocks of Booster Display Boxes, Booster Bundles, and Pokemon
Center Elite Trainer Boxes, broadcasting alerts to a Telegram channel.

## ⚠️ Project Status: Archived

This project is **paused at V1**. The bot is fully functional EXCEPT for
the product-fetch step, which is blocked by PokemonCenter.com's
anti-bot system (Imperva Incapsula).

**Working components:**
- Telegram bot integration ✅
- SQLite database for historical drop logging ✅
- Queue detection (with browser automation) ✅
- Stock change detection logic ✅
- Threading architecture (queue + product monitor in parallel) ✅
- Systemd service for auto-start ✅

**Blocked component:**
- Fetching `/products.json` from PokemonCenter.com — Incapsula serves
  a JavaScript challenge page that defeats: plain `requests`,
  `curl_cffi` with Chrome impersonation, and Playwright with stealth
  patches and homepage cookie warmup.

## Why It's Paused

Bypassing Incapsula reliably requires either:
- A paid proxy service like ScraperAPI (~$10/month) that maintains
  residential IP pools and CAPTCHA-solving infrastructure
- Significant ongoing reverse-engineering effort

This started as a free learning project and the cost-benefit didn't
justify ongoing fees, so it's archived in a working state for future
revisit if circumstances change.

## What I Learned Building This

- Raspberry Pi setup from scratch (imaging, headless SSH, systemd)
- Python concurrency with the threading module
- SQLite for local persistence
- Telegram bot API integration
- HTTP request anatomy and TLS fingerprinting
- The economics and architecture of anti-bot systems
- When to stop optimizing and accept paid solutions

## How to Resume Later

If you want to pick this back up:

1. Sign up for ScraperAPI (or similar): https://www.scraperapi.com
2. In `bot.py`, replace the `fetch_products()` function to route
   through the proxy: prefix the target URL with the ScraperAPI
   endpoint and your API key
3. Remove the Playwright/browser_fetch dependency (no longer needed)
4. Re-enable on the Pi:
   ```
   cd ~/pokemoncenter-bot
   git pull
   sudo systemctl start pokemon-bot
   ```

Alternatively, the bot's queue detection works without proxies, so a
queue-only V1.5 is possible if browser-based fetching becomes more
reliable in the future.

---

# Original Setup Documentation

## What V1 Does

- **Queue detection** — alerts when Pokemon Center's virtual queue
  opens (typically 5–25 minutes before a drop). Includes which Big 3
  products are currently staged on the site.
- **Drop detection** — alerts the moment a Big 3 product flips to
  in-stock.
- **Restock detection** — alerts when a sold-out item returns.
- **Historical logging** — every stock change and queue event is
  written to a local SQLite database.
- **Telegram broadcast** — anyone you invite to your channel gets
  the alerts on their phone instantly.

## The Big 3

The bot watches only three product types — everything else is ignored:

| Product | Description |
|---|---|
| Booster Display Box | 36 packs |
| Booster Bundle | 6 packs |
| Pokemon Center ETB | 11 packs + exclusive promo |

## Files in this Repo

| File | Purpose |
|---|---|
| `bot.py` | The bot itself |
| `browser_fetch.py` | Playwright-based fetcher (currently blocked by Incapsula) |
| `requirements.txt` | Python dependencies |
| `pokemon-bot.service` | Systemd config for auto-start on Pi boot |
| `.gitignore` | Excludes the database and log files from git |
| `README.md` | This file |

## Setup Instructions (for future reference)

### 1. Telegram Bot Setup

1. Message **@BotFather** on Telegram and send `/newbot`
2. Follow prompts to name your bot and get its token
3. Create a public Telegram channel
4. In channel settings → Administrators, add your bot with post permission

### 2. Pi Setup

```bash
# Clone the repo
git clone https://github.com/YOUR-USERNAME/pokemoncenter-bot.git
cd pokemoncenter-bot

# Install Python dependencies
pip3 install -r requirements.txt --break-system-packages

# Install Playwright browser (only if using browser_fetch.py)
sudo apt install -y libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxkbcommon0 libatspi2.0-0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 libnss3
python3 -m playwright install chromium

# Edit bot.py with your Telegram credentials
nano bot.py

# Test run
python3 bot.py

# Install as systemd service (auto-start on boot)
sudo cp pokemon-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pokemon-bot
sudo systemctl start pokemon-bot

# Watch logs
tail -f bot.log
```

## Cost Profile

| Item | Cost |
|---|---|
| Raspberry Pi (already owned) | $0 |
| Electricity | ~$1–2/year |
| Telegram | Free |
| Proxy service (required for product fetching) | ~$10/month |
