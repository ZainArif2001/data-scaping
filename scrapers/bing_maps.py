"""Bing Maps scraper — renders www.bing.com/maps in headless Chromium and
parses the `data-entity` JSON embedded in each result card.

Two modes:
  quick — a few query variants around the city (~10-30 results)
  deep  — grid sweep: query maps at every grid-cell centre of the city
          for near-complete coverage (slower, 10-20x results)

Fields: name, category, address, phone, website, opening hours.
"""
import json
from typing import Callable, List, Optional
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright
from .base import BaseScraper, Business
from .browser import UA, STEALTH_JS


class BingMapsScraper(BaseScraper):
    name = "Bing Maps"

    def search(self, keyword: str, city: str, country: str, limit: int = 50,
               points: Optional[list] = None,
               progress_cb: Optional[Callable] = None) -> List[Business]:
        seen, results = set(), []
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

                if points:
                    from .dedup import SYNONYMS
                    variants = [keyword] + SYNONYMS.get(keyword.strip().lower(), [])[:4]
                    targets = [
                        (variants[i % len(variants)], f"cp={lat}~{lon}&lvl=13")
                        for i, (lat, lon) in enumerate(points)
                    ]
                else:
                    loc = f"{city} {country}"
                    targets = [
                        (f"{keyword} {loc}", ""),
                        (f"{keyword} in {loc}", ""),
                        (f"{keyword} near {loc}", ""),
                    ]

                total = len(targets)
                for i, (q, viewport) in enumerate(targets):
                    if len(results) >= limit:
                        break
                    params = f"q={quote_plus(q)}"
                    if viewport:
                        params += f"&{viewport}"
                    url = f"https://www.bing.com/maps?{params}"
                    for ent in self._load_entities(page, url):
                        e = ent.get("entity", {})
                        name = (e.get("title") or "").strip()
                        key = name.lower()
                        if not name or key in seen:
                            continue
                        seen.add(key)
                        results.append(Business(
                            name=name,
                            address=e.get("address", ""),
                            phone=e.get("phone", ""),
                            website=e.get("website", ""),
                            category=e.get("primaryCategoryName", ""),
                            maps_url=url,
                        ))
                    if progress_cb:
                        progress_cb(i + 1, total)
            finally:
                browser.close()
        return self._fill_meta(results[:limit], keyword, city, country)

    def _load_entities(self, page, url: str) -> list:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_selector("[data-entity]", timeout=15000)
        except Exception:
            return []
        for _ in range(4):
            page.evaluate(
                "() => {const el=document.querySelector('div.b_lstcards');"
                " if(el) el.scrollTop=el.scrollHeight;}"
            )
            page.wait_for_timeout(1100)
        out = []
        for el in page.query_selector_all("[data-entity]"):
            try:
                out.append(json.loads(el.get_attribute("data-entity")))
            except (json.JSONDecodeError, TypeError):
                continue
        return out
