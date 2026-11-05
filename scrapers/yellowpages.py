"""Yellow Pages scraper.

Supported country directories:
  - United States  -> yellowpages.com
  - United Kingdom -> yell.com

Other countries: use OpenStreetMap (covers the whole world).
"""
import json
import re
from bs4 import BeautifulSoup
from typing import List, Optional
from urllib.parse import quote_plus

from .base import BaseScraper, Business
from .browser import fetch_rendered

UK_NAMES = {"uk", "united kingdom", "great britain", "england", "scotland", "wales"}
US_NAMES = {"us", "usa", "united states", "united states of america", "america"}


def _clean(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", text).strip() if text else ""


def _json_ld_items(soup: BeautifulSoup) -> list:
    items = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            data = data.get("itemListElement") or [data]
        if isinstance(data, list):
            items.extend(data)
    return items


class YellowPagesScraper(BaseScraper):
    name = "Yellow Pages"

    def search(self, keyword: str, city: str, country: str, limit: int = 50) -> List[Business]:
        c = country.strip().lower()
        if c in UK_NAMES:
            results = self._search_yell(keyword, city, limit)
        elif c in US_NAMES:
            results = self._search_yp(keyword, city, limit)
        else:
            raise ValueError(
                f"Yellow Pages supported only for US/UK. For '{country}' use OpenStreetMap."
            )
        return self._fill_meta(results, keyword, city, country)

    # ---------------- UK: yell.com ----------------
    def _search_yell(self, keyword: str, city: str, limit: int) -> List[Business]:
        slug = f"{quote_plus(keyword)}-{quote_plus(city)}".replace("+", "-")
        url = f"https://www.yell.com/s/{slug}.html"
        html = fetch_rendered(url, wait_selector="div.businessCapsule")
        soup = BeautifulSoup(html, "lxml")

        results = []
        for card in soup.select("div.businessCapsule"):
            name_el = card.select_one("h2.businessCapsule--name a, a.businessCapsule--name")
            if not name_el:
                continue
            addr_el = card.select_one(".businessCapsule--address")
            phone_el = card.select_one(".business--telephoneNumber, [itemprop='telephone']")
            rating = None
            rating_el = card.select_one("[class*='starRating'], .rating--stars span")
            if rating_el:
                m = re.search(r"([\d.]+)", rating_el.get("title", "") or rating_el.get_text())
                if m:
                    rating = float(m.group(1))
            reviews = None
            rev_el = card.select_one("[class*='review'] a, .businessCapsule--reviews")
            if rev_el:
                m = re.search(r"(\d+)", rev_el.get_text())
                if m:
                    reviews = int(m.group(1))
            website = ""
            web_el = card.select_one("a.businessCapsule--ctaItem[href*='website'], a[href*='businessWeb']")
            if web_el and web_el.get("href", "").startswith("http"):
                website = web_el["href"]
            results.append(Business(
                name=_clean(name_el.get_text()),
                address=_clean(addr_el.get_text() if addr_el else ""),
                phone=_clean(phone_el.get_text() if phone_el else ""),
                website=website,
                rating=rating,
                reviews=reviews,
                maps_url="https://www.yell.com" + name_el.get("href", "") if name_el.get("href", "").startswith("/") else name_el.get("href", ""),
            ))
            if len(results) >= limit:
                break
        return results

    # ---------------- US: yellowpages.com ----------------
    def _search_yp(self, keyword: str, city: str, limit: int) -> List[Business]:
        url = (
            "https://www.yellowpages.com/search"
            f"?search_terms={quote_plus(keyword)}&geo_location_terms={quote_plus(city)}"
        )
        html = fetch_rendered(url, wait_selector="div.result")
        soup = BeautifulSoup(html, "lxml")

        results = []
        for card in soup.select("div.result"):
            name_el = card.select_one("a.business-name")
            if not name_el:
                continue
            street = card.select_one(".street-address")
            locality = card.select_one(".locality")
            address = ", ".join(filter(None, [_clean(street.get_text() if street else ""),
                                              _clean(locality.get_text() if locality else "")]))
            phone_el = card.select_one(".phones")
            rating = None
            rating_el = card.select_one(".result-rating")
            if rating_el:
                classes = rating_el.get("class", [])
                words = ["one", "two", "three", "four", "five"]
                base = next((i + 1 for i, w in enumerate(words) if w in classes), 0)
                rating = float(base) + (0.5 if "half" in classes else 0.0) or None
            reviews = None
            count_el = card.select_one(".count")
            if count_el:
                m = re.search(r"(\d+)", count_el.get_text())
                if m:
                    reviews = int(m.group(1))
            website = ""
            web_el = card.select_one("a.track-visit-website")
            if web_el:
                website = web_el.get("href", "")
            results.append(Business(
                name=_clean(name_el.get_text()),
                address=address,
                phone=_clean(phone_el.get_text() if phone_el else ""),
                website=website,
                rating=rating,
                reviews=reviews,
                maps_url=name_el.get("href", ""),
            ))
            if len(results) >= limit:
                break
        return results
