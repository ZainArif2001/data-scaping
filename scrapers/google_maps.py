"""Google Maps scraper — renders google.com/maps search in headless Chromium.

Two phases:
  1. List cards (.Nv2PK): name, rating, reviews, category, short address
  2. Detail pane (per place URL): website, phone, full address — capped
     to keep runtime reasonable (~2s per place).

Google may rate-limit heavy use; keep limits modest.
"""
import re
from typing import Callable, List, Optional
from urllib.parse import quote_plus, urlparse, parse_qs

from playwright.sync_api import sync_playwright
from .base import BaseScraper, Business
from .browser import UA, STEALTH_JS

DETAIL_CAP = 25
_HOURS_RE = re.compile(r"\s*(Open|Closed|Opens|Closes|Opening|Closing).*$", re.I)
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


class GoogleMapsScraper(BaseScraper):
    name = "Google Maps"

    def search(self, keyword: str, city: str, country: str, limit: int = 50,
               points: Optional[list] = None,
               progress_cb: Optional[Callable] = None,
               detail_limit: Optional[int] = None,
               detail_cb: Optional[Callable] = None) -> List[Business]:
        if points:
            from .dedup import SYNONYMS
            variants = [keyword] + SYNONYMS.get(keyword.strip().lower(), [])[:4]
            urls = [
                f"https://www.google.com/maps/search/"
                f"{quote_plus(f'{variants[i % len(variants)]}')}/@{lat},{lon},14z"
                for i, (lat, lon) in enumerate(points)
            ]
        else:
            urls = [f"https://www.google.com/maps/search/"
                    f"{quote_plus(f'{keyword} {city} {country}')}"]
        cards, details = self._scrape(urls, limit, progress_cb,
                                    detail_limit=detail_limit, detail_cb=detail_cb)

        results, seen = [], set()
        for c in cards:
            name = (c.get("name") or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            d = details.get(c.get("url", ""), {})
            results.append(Business(
                name=name,
                address=d.get("address") or c.get("address", ""),
                phone=d.get("phone") or c.get("phone", ""),
                website=d.get("website", ""),
                rating=c.get("rating"),
                reviews=c.get("reviews"),
                category=c.get("category", ""),
                maps_url=c.get("url") or url,
            ))
            if len(results) >= limit:
                break
        return self._fill_meta(results, keyword, city, country)

    def _scrape(self, urls: list, limit: int, progress_cb=None,
                detail_limit: Optional[int] = None, detail_cb=None):
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            try:
                ctx = browser.new_context(
                    user_agent=UA, viewport={"width": 1366, "height": 900}, locale="en-GB"
                )
                ctx.add_init_script(STEALTH_JS)
                page = ctx.new_page()

                all_cards, details = {}, {}
                total = len(urls)
                for i, url in enumerate(urls):
                    if len(all_cards) >= limit * 2:
                        break
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=45000)
                        if "consent.google" in page.url:
                            try:
                                page.click(
                                    "button:has-text('Reject all'), button:has-text('Accept all')",
                                    timeout=5000)
                            except Exception:
                                pass
                        try:
                            page.wait_for_selector("div[role='feed']", timeout=15000)
                        except Exception:
                            if progress_cb:
                                progress_cb(i + 1, total)
                            continue
                        last = 0
                        for _ in range(20):
                            count = page.evaluate(
                                "document.querySelectorAll('div.Nv2PK').length")
                            if count >= limit * 2 or count == last:
                                break
                            last = count
                            page.evaluate(
                                "const f=document.querySelector('div[role=feed]');"
                                " if(f) f.scrollTop=f.scrollHeight;")
                            page.wait_for_timeout(1000)
                        for c in page.evaluate(CARD_JS):
                            key = (c.get("name") or "").strip().lower()
                            if key and key not in all_cards:
                                all_cards[key] = c
                    except Exception:
                        pass
                    if progress_cb:
                        progress_cb(i + 1, total)

                cards = list(all_cards.values())
                dcap = detail_limit if detail_limit is not None else DETAIL_CAP
                for di, c in enumerate(cards[:dcap]):
                    href = c.get("url")
                    if not href:
                        continue
                    details[href] = self._detail(page, href)
                    if detail_cb:
                        detail_cb(di + 1, min(dcap, len(cards)))
                return cards, details
            finally:
                browser.close()

    def _detail(self, page, href: str) -> dict:
        out = {}
        try:
            page.goto(href, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("h1", timeout=10000)
            page.wait_for_timeout(600)
            web = page.query_selector('a[data-item-id="authority"]')
            if web:
                link = web.get_attribute("href") or ""
                if link.startswith("/url?"):
                    link = parse_qs(urlparse(link).query).get("q", [""])[0]
                out["website"] = link
            ph = page.query_selector('button[data-item-id^="phone"]')
            if ph:
                out["phone"] = (ph.get_attribute("aria-label") or "").replace("Phone:", "").strip()
            ad = page.query_selector('button[data-item-id="address"]')
            if ad:
                out["address"] = (ad.get_attribute("aria-label") or "").replace("Address:", "").strip()
        except Exception:
            pass
        return out


CARD_JS = """
() => {
  const out = [];
  document.querySelectorAll('div.Nv2PK').forEach(card => {
    const name = card.querySelector('.qBF1Pd')?.textContent?.trim()
              || card.querySelector('a.hfpxzc')?.getAttribute('aria-label') || '';
    const ratingTxt = card.querySelector('.MW4etd')?.textContent?.trim() || '';
    const revTxt = card.querySelector('.UY7F9')?.textContent?.trim() || '';
    const lines = [...card.querySelectorAll('.W4Efsd')].map(d => d.textContent.trim());
    let address = '', category = '', phone = '';
    const hoursWord = /^(open|closed|opens|closes|opening|closing)/i;
    const addrLine = [...lines].reverse().find(
      l => l.includes('·') && !hoursWord.test(l.trim())) || '';
    if (addrLine) {
      const parts = addrLine.split('·').map(s => s.trim()).filter(Boolean);
      category = parts[0] || '';
      address = parts.slice(1).join(', ')
        .replace(/\\s*(Open|Closed|Opens|Closes).*$/i, '')
        .replace(/^[\\s,·]+/, '').replace(/[\\s,·]+$/, '');
    }
    const phoneMatch = card.innerText.match(/\\+?\\d[\\d\\s().-]{7,}\\d/);
    if (phoneMatch) phone = phoneMatch[0].trim();
    out.push({
      name,
      rating: ratingTxt ? parseFloat(ratingTxt) : null,
      reviews: revTxt ? parseInt(revTxt.replace(/[^0-9]/g, '')) : null,
      category, address, phone,
      url: card.querySelector('a.hfpxzc')?.href || '',
    });
  });
  return out;
}
"""
