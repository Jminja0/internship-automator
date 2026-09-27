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


def goto(page, url, timeout_ms=15000):
    """Navigate to a listing's apply URL and wait for it to settle.

    page.goto() already waits for the page to load. The extra
    networkidle wait below is best-effort only -- some sites (heavy
    analytics/tracking) never go fully idle, so a timeout here is
    expected and shouldn't stop the run.
    """
    page.goto(url, timeout=timeout_ms)
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass