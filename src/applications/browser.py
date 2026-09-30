"""Thin wrapper around Playwright for opening application pages."""

from contextlib import contextmanager

from playwright.sync_api import sync_playwright


@contextmanager
def open_browser(headless=False):
    """Launch a browser and yield a ready-to-use page.

    headless=False by default so you can watch (and take over) the
    form filling in real time -- this tool never submits anything on
    its own.
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

        try:
            yield page
        finally:
            browser.close()


def goto(page, url, timeout_ms=15000, settle_ms=5000):
    """Navigate to a listing's apply URL and wait for it to settle.

    The page is usable at DOMContentLoaded; waiting for the full `load` event
    can stall on trackers and ads. The extra networkidle wait is best-effort
    and short, because some sites (heavy analytics) never go fully idle and a
    timeout here is expected, not an error.
    """
    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=settle_ms)
    except Exception:
        pass
