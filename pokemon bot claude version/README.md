# 🃏 Pokemon Center Drop Bot — V1 (Pi Edition)

Watches PokemonCenter.com for drops/restocks of your Big 3 products and
broadcasts alerts to a Telegram channel. Runs on a Raspberry Pi at home
using your residential internet — no cloud fees, no proxy, no blocking.

---

## What V1 Does

- **Queue detection** — alerts when Pokemon Center's virtual queue opens
  (typically 5–25 minutes before a drop). Alert includes which of your
  Big 3 are staged and about to drop.
- **Drop detection** — alerts the moment a Big 3 product flips to in-stock.
- **Restock detection** — alerts when a sold-out item returns.
- **Historical logging** — every stock change is written to a local
  SQLite database for analyzing drop patterns later.
- **Broadcast to a Telegram channel** — anyone you invite to the channel
  gets the alerts.

## The Big 3

The bot watches only three product types — everything else is ignored:

| Product | Description |
|---|---|
| **Booster Display Box** | 36 packs |
| **Booster Bundle** | 6 packs |
| **Pokemon Center ETB** | 11 packs + exclusive promo |

---

## Files in this Repo

| File | Purpose |
|---|---|
| `bot.py` | The bot itself |
| `requirements.txt` | Python libraries to install (just `requests`) |
| `pokemon-bot.service` | Systemd config for auto-start on Pi boot |
| `.gitignore` | Tells git to ignore the database & log files |
| `README.md` | This file |

---

## Setup Instructions

Detailed step-by-step Pi setup will be covered when you set up the Pi.
The overview below is just the big picture.

### 1. Create a Telegram Bot (5 minutes)

1. Open Telegram on your phone
2. Message **@BotFather** and send `/newbot`
3. Give it a name and username (username must end in `bot`)
4. BotFather gives you a **token** — copy it, you'll paste it into `bot.py`

### 2. Create a Telegram Channel (2 minutes)

1. In Telegram, tap the pencil icon → **New Channel**
2. Name it (e.g. "Pokemon Center Drops")
3. Make it **Public** with a username for now (easier than private channels)
4. Go to channel settings → **Administrators** → **Add Administrator**
5. Search for your bot's username and add it with post permission

### 3. Configure the Bot

Open `bot.py` and update two lines:

```python
TELEGRAM_BOT_TOKEN = "paste your token from BotFather here"
TELEGRAM_CHAT_ID   = "@yourchannelname"   # the public username of your channel
```

### 4. Install on the Pi

Rough outline — walked through in detail when setting up the Pi:

```bash
# clone this repo onto the Pi
git clone https://github.com/YOUR-USERNAME/pokemon-bot.git
cd pokemon-bot

# install dependencies
pip3 install -r requirements.txt

# test run
python3 bot.py

# install as a service so it auto-starts on boot
sudo cp pokemon-bot.service /etc/systemd/system/
sudo systemctl enable pokemon-bot
sudo systemctl start pokemon-bot
```

---

## What Each Alert Looks Like

**Queue alert** (5–25 min before drop):
> 🚨 POKEMON CENTER QUEUE IS LIVE
> 
> Staged & ready to drop:
>   🎯 Booster Display Box (36 packs)
>   🎯 Pokemon Center ETB
> 
> A drop is imminent in the next 5–25 min.
> 👉 Open Pokemon Center and get in line

**Drop alert** (moment product goes live):
> 🚨 RESTOCK — ADD TO CART NOW
> 
> Booster Display Box (36 packs)
> 💰 $161.64
> 🔄 Flipped from sold out → in stock!
> 👉 Open product page

---

## The Database

Every stock change is logged to `pokemon_drops.db` on the Pi. Three tables:

- **stock_changes** — every NEW_DROP, RESTOCK, SOLD_OUT, and STAGED event
- **queue_events** — every QUEUE_OPENED and QUEUE_CLOSED event
- **product_state** — current known state of each variant (used by bot)

After running a few weeks, you can start querying this data to see:
- What time drops typically happen for each product
- How long products stay in stock
- Which days of the week drops favor

This becomes the foundation for V2's pre-notification feature.

---

## Cost

| Item | Cost |
|---|---|
| Raspberry Pi (already owned) | $0 |
| Electricity | ~$1–2/year |
| Telegram | Free |
| **Total** | **~$0/month** |
