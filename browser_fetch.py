"""
Browser-based fetcher for Pokemon Center.

Uses Playwright to launch a real Chromium browser in the background,
which can solve Incapsula's JavaScript challenges. Slower than plain
HTTP but reliable against bot detection.

One browser instance is kept alive for the lifetime of the bot to
avoid the overhead of launching Chromium on every fetch.
"""

import threading
import json
from playwright.sync_api import sync_playwright


# Keep one browser + context alive across all fetches
_playwright   = None
_browser      = None
_context      = None
_browser_lock = threading.Lock()


def _ensure_browser():
    """Lazy-start the browser on first use, then keep it alive."""
    global _playwright, _browser, _context
    if _browser is None:
        print("  🌐 Launching headless Chromium...")
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        _context = _browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/Phoenix",
        )
        print("  ✅ Browser ready")


def fetch_url_json(url, timeout_ms=30000):
    """
    Navigate to a URL and return the response body parsed as JSON.
    The browser handles any JS challenges automatically.
    Returns the parsed JSON dict, or raises an exception on failure.
    """
    with _browser_lock:
        _ensure_browser()
        page = _context.new_page()
        try:
            # Navigate and wait for the network to settle (challenge solved)
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            # The JSON body is rendered inside a <pre> tag by the browser
            body = page.evaluate("() => document.body.innerText")
            return json.loads(body)
        finally:
            page.close()


def fetch_url_html(url, timeout_ms=30000):
    """
    Navigate to a URL and return the final URL + rendered HTML.
    Returns a tuple: (final_url_lowercase, html_body_lowercase).
    """
    with _browser_lock:
        _ensure_browser()
        page = _context.new_page()
        try:
            response = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            final_url = page.url.lower()
            html      = page.content().lower()
            return final_url, html
        finally:
            page.close()


def close_browser():
    """Clean shutdown (only matters if you're manually testing)."""
    global _playwright, _browser, _context
    if _browser is not None:
        _browser.close()
        _browser = None
    if _playwright is not None:
        _playwright.stop()
        _playwright = None
