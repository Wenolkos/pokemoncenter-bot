"""
Browser-based fetcher for Pokemon Center.

Uses Playwright to launch a real Chromium browser in the background,
which can solve Incapsula's JavaScript challenges.

Each calling thread gets its OWN browser instance (Playwright's sync
API can't be shared across threads). This means two browsers run
total — one for the queue monitor, one for the product monitor.
"""

import threading
import json
from playwright.sync_api import sync_playwright


# Thread-local storage — each thread gets its own browser/context
_thread_local = threading.local()


def _ensure_browser():
    """Lazy-start a browser for the current thread on first use."""
    if not hasattr(_thread_local, "browser") or _thread_local.browser is None:
        print(f"  🌐 Launching headless Chromium for thread {threading.current_thread().name}...")
        _thread_local.playwright = sync_playwright().start()
        _thread_local.browser = _thread_local.playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
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
        print(f"  ✅ Browser ready for thread {threading.current_thread().name}")


def fetch_url_json(url, timeout_ms=30000):
    """
    Navigate to a URL and return the response body parsed as JSON.
    Must be called from the same thread that will own its browser.
    """
    _ensure_browser()
    page = _thread_local.context.new_page()
    try:
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        body = page.evaluate("() => document.body.innerText")
        return json.loads(body)
    finally:
        page.close()


def fetch_url_html(url, timeout_ms=30000):
    """
    Navigate to a URL and return (final_url, html) both lowercased.
    Must be called from the same thread that will own its browser.
    """
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
    if hasattr(_thread_local, "browser") and _thread_local.browser is not None:
        _thread_local.browser.close()
        _thread_local.browser = None
    if hasattr(_thread_local, "playwright") and _thread_local.playwright is not None:
        _thread_local.playwright.stop()
        _thread_local.playwright = None
