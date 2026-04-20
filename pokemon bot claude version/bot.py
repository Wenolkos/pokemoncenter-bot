"""
Pokemon Center Drop Bot — V1 (Pi Edition)
==========================================
Watches PokemonCenter.com for drops/restocks of your Big 3 products
and broadcasts alerts to a Telegram channel.

  Big 3:
    - Booster Display Box (36 packs)
    - Booster Bundle (6 packs)
    - Pokemon Center Elite Trainer Box (PC ETB)

Three detection layers, earliest warning to latest:
  1. Staged product detection (always running, passive)
     Products loaded on site but marked unavailable → we track these.

  2. Queue monitor (every 30s)
     Detects when Pokemon Center's virtual waiting room activates.
     Fires 5–25 minutes before products go live.
     The alert includes which staged products are about to drop.

  3. Product monitor (every 25s)
     Fires the moment a Big 3 product flips unavailable → available.

Every stock change is logged to a local SQLite database for building
historical drop timing data that can power future features.
"""

import requests
import os
import time
import sqlite3
import threading
from datetime import datetime, timezone
from urllib.parse import quote

import browser_fetch


# ============================================================
# CONFIGURATION — Edit these before running
# ============================================================

# Telegram bot token from @BotFather (see README for how to get one)
TELEGRAM_BOT_TOKEN = "PASTE_YOUR_BOT_TOKEN_HERE"

# Telegram channel ID where alerts are broadcast.
# For public channels: use "@yourchannelname"
# For private channels: use the numeric ID (starts with -100...)
TELEGRAM_CHAT_ID = "@yourchannelname"

# Polling intervals (seconds)
PRODUCT_POLL_INTERVAL = 25   # how often to check for drops
QUEUE_POLL_INTERVAL   = 30   # how often to check the queue

# File paths (relative to wherever the bot runs)
DB_FILE    = "pokemon_drops.db"  # SQLite database for historical logs

# ============================================================
# BIG 3 KEYWORDS — Only products matching these are watched
# ============================================================
BIG_3_KEYWORDS = [
    "booster display",
    "booster bundle",
    "pokemon center elite trainer",
    "pokémon center elite trainer",
]


# ============================================================
# BROWSER HEADER ROTATION
# Makes requests look like real browsers, not a bot.
# Running from a Pi on your home internet means your IP is
# residential and not flagged — so this just needs to be
# plausible, not airtight.
# ============================================================
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15",
]
_ua_index = 0
_ua_lock  = threading.Lock()

def get_headers():
    """Return a full set of browser-like headers with a rotating User-Agent."""
    global _ua_index
    with _ua_lock:
        ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
        _ua_index += 1
    return {
        "User-Agent":                ua,
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":           "en-US,en;q=0.9",
        "Accept-Encoding":           "gzip, deflate, br",
        "Cache-Control":             "no-cache",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


# ============================================================
# SHARED STATE (read/written by both threads)
# ============================================================
_staged_products     = {}                       # {display_name: url}
_staged_lock         = threading.Lock()
_queue_alert_sent    = False
_queue_alert_lock    = threading.Lock()


# ============================================================
# DATABASE — SQLite for historical data
#
# Why SQLite? Zero setup — it's just a file on the Pi.
# No server, no config, no cost. Perfect for V1.
#
# Two tables:
#   stock_changes   — every time a product flips stock state
#   queue_events    — every time the queue opens or closes
#
# Later, you can query this to answer questions like:
#   "What day/time do Booster Display Boxes usually drop?"
#   "How long does a typical drop stay in stock?"
# ============================================================

def init_database():
    """Create database tables if they don't already exist."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS stock_changes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,
            product_id    TEXT NOT NULL,
            variant_id    TEXT NOT NULL,
            product_title TEXT NOT NULL,
            variant_title TEXT,
            price         TEXT,
            event_type    TEXT NOT NULL,
            product_url   TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS queue_events (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc TEXT NOT NULL,
            event_type    TEXT NOT NULL,
            reason        TEXT,
            staged_items  TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS product_state (
            state_key      TEXT PRIMARY KEY,
            is_available   INTEGER NOT NULL,
            last_seen_utc  TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print("💾 Database initialized")


def now_utc():
    """ISO-format UTC timestamp for database rows."""
    return datetime.now(timezone.utc).isoformat()


def log_stock_change(product, variant, event_type):
    """Record a stock change (NEW_DROP, RESTOCK, SOLD_OUT, STAGED)."""
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        INSERT INTO stock_changes
        (timestamp_utc, product_id, variant_id, product_title,
         variant_title, price, event_type, product_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        now_utc(),
        str(product["id"]),
        str(variant["id"]),
        product["title"],
        variant.get("title"),
        variant.get("price"),
        event_type,
        f"https://www.pokemoncenter.com/products/{product['handle']}",
    ))
    conn.commit()
    conn.close()


def log_queue_event(event_type, reason=None, staged_items=None):
    """Record a queue event (QUEUE_OPENED, QUEUE_CLOSED)."""
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        INSERT INTO queue_events (timestamp_utc, event_type, reason, staged_items)
        VALUES (?, ?, ?, ?)
    """, (now_utc(), event_type, reason, staged_items))
    conn.commit()
    conn.close()


def get_last_availability(state_key):
    """Returns True, False, or None — last known availability of a variant."""
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute(
        "SELECT is_available FROM product_state WHERE state_key = ?",
        (state_key,),
    ).fetchone()
    conn.close()
    return bool(row[0]) if row else None


def set_availability(state_key, is_available):
    """Upsert current availability for a variant."""
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        INSERT INTO product_state (state_key, is_available, last_seen_utc)
        VALUES (?, ?, ?)
        ON CONFLICT(state_key) DO UPDATE SET
            is_available = excluded.is_available,
            last_seen_utc = excluded.last_seen_utc
    """, (state_key, 1 if is_available else 0, now_utc()))
    conn.commit()
    conn.close()


# ============================================================
# BIG 3 MATCHING & DISPLAY NAMES
# ============================================================

def is_big_3(title):
    """True if a product title matches one of the Big 3."""
    title_lower = title.lower()
    return any(kw in title_lower for kw in BIG_3_KEYWORDS)


def get_short_name(title):
    """Collapse long product titles into short readable labels."""
    t = title.lower()
    if "booster display" in t:
        return "Booster Display Box (36 packs)"
    if "booster bundle" in t:
        return "Booster Bundle (6 packs)"
    if "pokemon center elite trainer" in t or "pokémon center elite trainer" in t:
        return "Pokemon Center ETB"
    return title


# ============================================================
# TELEGRAM NOTIFICATIONS
#
# Telegram's bot API is dead simple: POST to sendMessage with
# your bot token, chat ID, and message text. Bot posts show up
# in the target channel instantly.
#
# Supports Markdown for formatting and clickable links.
# ============================================================

def send_telegram(message, silent=False):
    """
    Send a message to the configured Telegram channel.
    Uses Markdown for bold/italic/links. Messages with emojis
    work natively — no encoding headaches like ntfy had.
    """
    if TELEGRAM_BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        print("  ⚠️  TELEGRAM_BOT_TOKEN not configured — skipping notification")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id":                  TELEGRAM_CHAT_ID,
            "text":                     message,
            "parse_mode":               "Markdown",
            "disable_web_page_preview": False,
            "disable_notification":     silent,  # True = silent for heartbeats
        }, timeout=10)

        if r.status_code == 200:
            print(f"  ✅ Telegram sent")
            return True
        else:
            print(f"  ❌ Telegram error {r.status_code}: {r.text[:200]}")
            return False
    except Exception as e:
        print(f"  ❌ Telegram send failed: {e}")
        return False


# ============================================================
# FETCH PRODUCTS
# ============================================================

def fetch_products():
    """
    Fetch Pokemon Center's product catalog via a real headless browser.
    This defeats Incapsula's JavaScript challenge that blocks plain HTTP.
    """
    url = "https://www.pokemoncenter.com/products.json?limit=250"
    try:
        data = browser_fetch.fetch_url_json(url)
        return data.get("products", [])
    except Exception as e:
        raise Exception(f"Browser fetch failed: {e}")


# ============================================================
# QUEUE DETECTION
# ============================================================

def check_queue_active():
    """
    Detect the Pokemon Center virtual queue by examining the
    homepage response for queue signals.
      Returns (True,  reason)  — queue active
              (False, None)    — queue not active
              (None,  None)    — couldn't check (network error)
    """
    try:
        final_url, body = browser_fetch.fetch_url_html("https://www.pokemoncenter.com")

        # Signal 1: redirect to queue/waiting URL
        if any(w in final_url for w in ["queue", "waiting", "waitingroom"]):
            return True, "redirected to queue URL"

        # Signal 2: explicit queue page text
        for signal in [
            "you are in a queue",
            "you are in line",
            "waiting room",
            "queue position",
            "virtual queue",
        ]:
            if signal in body:
                return True, f"queue text detected: '{signal}'"

        # Signal 3: high-demand body text (incapsula signal in browser context)
        for signal in ["please wait", "high demand", "queue-it"]:
            if signal in body:
                return True, f"queue-like text: '{signal}'"

        return False, None

    except Exception as e:
        print(f"  ⚠️  Queue check error: {e}")
        return None, None


# ============================================================
# MESSAGE BUILDERS
# ============================================================

def build_queue_open_message():
    """Queue-opened alert, including currently staged Big 3 products."""
    with _staged_lock:
        staged = dict(_staged_products)

    if staged:
        lines = "\n".join(f"  🎯 [{name}]({url})" for name, url in staged.items())
        staged_block = f"\n*Staged & ready to drop:*\n{lines}\n"
    else:
        staged_block = "\n_No Big 3 products currently staged — drop contents unknown._\n"

    return (
        "🚨 *POKEMON CENTER QUEUE IS LIVE*\n"
        f"{staged_block}"
        "\nA drop is imminent in the next 5–25 min.\n"
        "[👉 Open Pokemon Center and get in line](https://www.pokemoncenter.com)"
    )


def build_queue_close_message():
    return (
        "✅ *Queue Closed*\n\n"
        "Products may now be live — check the site.\n"
        "Tip: rejoin the queue from the homepage for a second shot at "
        "remaining inventory.\n\n"
        "[Open Pokemon Center](https://www.pokemoncenter.com)"
    )


def build_stock_message(short_name, product_url, price, event_type):
    """Message for NEW_DROP or RESTOCK events."""
    if event_type == "NEW_DROP":
        header = "🚨 *NEW DROP — ADD TO CART NOW*"
        line   = "🆕 Just appeared as in-stock!"
    else:  # RESTOCK
        header = "🚨 *RESTOCK — ADD TO CART NOW*"
        line   = "🔄 Flipped from sold out → in stock!"

    return (
        f"{header}\n\n"
        f"*{short_name}*\n"
        f"💰 ${price}\n"
        f"{line}\n\n"
        f"[👉 Open product page]({product_url})"
    )


# ============================================================
# QUEUE MONITOR LOOP (runs in background thread)
# ============================================================

def queue_monitor_loop():
    global _queue_alert_sent
    print("🔍 Queue monitor started — checking every 30s")

    while True:
        try:
            is_active, reason = check_queue_active()

            if is_active:
                with _queue_alert_lock:
                    if not _queue_alert_sent:
                        print(f"  🚨 QUEUE DETECTED ({reason})")
                        with _staged_lock:
                            staged_items_list = "|".join(_staged_products.keys())
                        log_queue_event("QUEUE_OPENED", reason, staged_items_list)
                        send_telegram(build_queue_open_message())
                        _queue_alert_sent = True
                    else:
                        print(f"  ℹ️  Queue still active at {time.strftime('%H:%M:%S')}")

            elif is_active is False:
                with _queue_alert_lock:
                    if _queue_alert_sent:
                        print("  ✅ Queue closed")
                        log_queue_event("QUEUE_CLOSED")
                        send_telegram(build_queue_close_message())
                        _queue_alert_sent = False
                    else:
                        print(f"  ✅ Queue check {time.strftime('%H:%M:%S')} — idle")

        except Exception as e:
            print(f"  ⚠️  Queue monitor error: {e}")

        time.sleep(QUEUE_POLL_INTERVAL)


# ============================================================
# PRODUCT MONITOR LOOP (main thread)
# ============================================================

def product_monitor_loop():
    print(f"📦 Product monitor started — checking every {PRODUCT_POLL_INTERVAL}s")
    print(f"   Watching: Booster Display | Booster Bundle | PC ETB\n")

    last_heartbeat = time.time()

    while True:
        try:
            products = fetch_products()
            print(f"📦 Checked {len(products)} products at {time.strftime('%H:%M:%S')}")

            new_staged = {}
            big_3_count = 0

            for product in products:
                if not is_big_3(product["title"]):
                    continue
                big_3_count += 1

                product_url = f"https://www.pokemoncenter.com/products/{product['handle']}"
                price       = product["variants"][0]["price"]

                for variant in product["variants"]:
                    state_key = f"{product['id']}:{variant['id']}"
                    was_available = get_last_availability(state_key)
                    is_available  = variant["available"]

                    display_title = product["title"]
                    if len(product["variants"]) > 1:
                        display_title += f" — {variant['title']}"
                    short_name = get_short_name(display_title)

                    if is_available:
                        if was_available is None:
                            # First time seeing it, and it's live
                            print(f"  🆕 NEW DROP: {short_name}")
                            log_stock_change(product, variant, "NEW_DROP")
                            send_telegram(build_stock_message(
                                short_name, product_url, price, "NEW_DROP"
                            ))

                        elif was_available is False:
                            # Was staged/sold out, now live = the drop!
                            print(f"  🔴→🟢 RESTOCK: {short_name}")
                            log_stock_change(product, variant, "RESTOCK")
                            send_telegram(build_stock_message(
                                short_name, product_url, price, "RESTOCK"
                            ))

                    else:
                        # Product is on site but not purchasable — staged
                        new_staged[short_name] = product_url

                        if was_available is None:
                            print(f"  👁️  STAGED: {short_name}")
                            log_stock_change(product, variant, "STAGED")
                        elif was_available is True:
                            print(f"  🟢→⚫ SOLD OUT: {short_name}")
                            log_stock_change(product, variant, "SOLD_OUT")

                    set_availability(state_key, is_available)

            # Update shared staged list for the queue monitor
            with _staged_lock:
                _staged_products.clear()
                _staged_products.update(new_staged)

            if big_3_count == 0:
                print("  (No Big 3 products found)")
            elif new_staged:
                print(f"  👁️  {len(new_staged)} Big 3 staged on site")

            # Hourly silent heartbeat to Telegram
            if time.time() - last_heartbeat > 3600:
                send_telegram(
                    "💓 Bot heartbeat — still watching for drops",
                    silent=True,
                )
                last_heartbeat = time.time()

        except Exception as e:
            print(f"  ⚠️  Product monitor error: {e}")

        time.sleep(PRODUCT_POLL_INTERVAL)


# ============================================================
# STARTUP
# ============================================================

if __name__ == "__main__":
    print("=" * 55)
    print("  🃏 Pokemon Center Drop Bot — V1 (Pi Edition)")
    print("=" * 55)
    print(f"  💬 Telegram : {TELEGRAM_CHAT_ID}")
    print(f"  ⏱️  Products : every {PRODUCT_POLL_INTERVAL}s")
    print(f"  🚦 Queue    : every {QUEUE_POLL_INTERVAL}s")
    print(f"  💾 DB       : {DB_FILE}")
    print("=" * 55)
    print()

    init_database()

    # Queue monitor runs in a background thread (daemon=True means
    # it stops automatically when the main program exits)
    queue_thread = threading.Thread(target=queue_monitor_loop, daemon=True)
    queue_thread.start()

    # Product monitor runs in main thread forever
    product_monitor_loop()
