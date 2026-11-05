"""Shared headless-browser fetcher (Playwright) for protected sites."""
from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-GB', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


def fetch_rendered(url: str, wait_selector: str = None, timeout_ms: int = 45000) -> str:
    """Load `url` in headless Chromium, wait for content, return page HTML."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        try:
            ctx = browser.new_context(
                user_agent=UA,
                viewport={"width": 1366, "height": 900},
                locale="en-GB",
            )
            ctx.add_init_script(STEALTH_JS)
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            # give Cloudflare/JS challenge time to resolve
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=20000)
                except Exception:
                    pass
            else:
                page.wait_for_timeout(4000)
            return page.content()
        finally:
            browser.close()
