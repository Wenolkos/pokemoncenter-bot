"""
Browser-based fetcher for Pokemon Center.

This version combines two techniques to bypass Incapsula:

1. playwright-stealth — patches the browser to hide headless
   fingerprints (webdriver flag, missing plugins, fake languages, etc.)

2. Homepage warmup — visits the homepage first so Incapsula sets
   its session cookie; subsequent JSON fetches reuse that cookie,
   just like a real user who browsed before hitting an API.

Each calling thread gets its own browser instance (Playwright's
sync API can't be shared across threads). The Incapsula cookie
persists inside each thread's browser context.
"""

import threading
import json
import time
from playwright.sync_api import sync_playwright

# playwright-stealth has had a couple API versions — handle both
try:
    from playwright_stealth import Stealth
    _STEALTH_MODE = "new"
except ImportError:
    try:
        from playwright_stealth import stealth_sync
        _STEALTH_MODE = "old"
    except ImportError:
        _STEALTH_MODE = None
        print("  ⚠️  playwright-stealth not installed — continuing without it")


# Thread-local storage — each thread gets its own browser/context
_thread_local = threading.local()


def _ensure_browser():
    """Lazy-start a browser for the current thread on first use,
    apply stealth patches, and warm up on the homepage."""
    if getattr(_thread_local, "browser", None) is not None:
        return

    thread_name = threading.current_thread().name
    print(f"  🌐 Launching Chromium for thread {thread_name}...")

    _thread_local.playwright = sync_playwright().start()
    _thread_local.browser = _thread_local.playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
        ],
    )
    _thread_local.context = _thread_local.browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        timezone_id="America/Phoenix",
    )

    # Apply stealth patches (old API: patch a page directly)
    if _STEALTH_MODE == "old":
        page_for_stealth = _thread_local.context.new_page()
        try:
            stealth_sync(page_for_stealth)
        except Exception as e:
            print(f"  ⚠️  stealth_sync failed: {e}")
        page_for_stealth.close()

    # New API: wraps the context
    if _STEALTH_MODE == "new":
        try:
            Stealth().apply_stealth_sync(_thread_local.context)
        except Exception as e:
            print(f"  ⚠️  Stealth apply failed: {e}")

    print(f"  ✅ Browser ready for thread {thread_name} — warming up...")

    # Warmup: visit the homepage so Incapsula sets a session cookie.
    # This cookie then carries over to the JSON fetch.
    warmup_page = _thread_local.context.new_page()
    try:
        warmup_page.goto(
            "https://www.pokemoncenter.com",
            wait_until="networkidle",
            timeout=45000,
        )
        # Give Incapsula a moment to finish its JS challenge
        time.sleep(3)
        print(f"  ✅ Homepage warmup complete for thread {thread_name}")
    except Exception as e:
        print(f"  ⚠️  Homepage warmup had issues: {e}")
    finally:
        warmup_page.close()


def fetch_url_json(url, timeout_ms=45000):
    """
    Navigate to a JSON URL and return the parsed body.
    Relies on Incapsula cookies set during homepage warmup.
    """
    _ensure_browser()
    page = _thread_local.context.new_page()
    try:
        response = page.goto(url, wait_until="networkidle", timeout=timeout_ms)

        if response is None:
            raise Exception("No response received from page.goto")

        body_bytes = response.body()
        text = body_bytes.decode("utf-8", errors="replace")

        # Sanity check — if we got HTML back, the challenge beat us
        if text.lstrip().startswith("<"):
            preview = text[:150].replace("\n", " ")
            raise Exception(f"Got HTML instead of JSON (Incapsula challenge?): {preview}")

        return json.loads(text)
    finally:
        page.close()


def fetch_url_html(url, timeout_ms=45000):
    """Navigate to a URL and return (final_url_lowercase, html_lowercase)."""
    _ensure_browser()
    page = _thread_local.context.new_page()
    try:
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        final_url = page.url.lower()
        html      = page.content().lower()
        return final_url, html
    finally:
        page.close()


def close_browser():
    """Clean up the current thread's browser."""
    if getattr(_thread_local, "browser", None) is not None:
        _thread_local.browser.close()
        _thread_local.browser = None
    if getattr(_thread_local, "playwright", None) is not None:
        _thread_local.playwright.stop()
        _thread_local.playwright = None
