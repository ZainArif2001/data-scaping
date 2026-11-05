"""Hotfrog business directory scraper (plain HTTP — no browser needed).

Country domains: hotfrog.com (US), hotfrog.co.uk, hotfrog.in,
hotfrog.com.au, hotfrog.ae, hotfrog.ca, hotfrog.co.nz ...
"""
import re
import requests
from bs4 import BeautifulSoup
from typing import List, Optional
from urllib.parse import quote

from .base import BaseScraper, Business

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

COUNTRY_DOMAIN = {
    "united kingdom": "hotfrog.co.uk", "uk": "hotfrog.co.uk",
    "england": "hotfrog.co.uk", "scotland": "hotfrog.co.uk", "wales": "hotfrog.co.uk",
    "united states": "hotfrog.com", "usa": "hotfrog.com", "us": "hotfrog.com",
    "india": "hotfrog.in",
    "australia": "hotfrog.com.au",
    "uae": "hotfrog.ae", "united arab emirates": "hotfrog.ae",
    "canada": "hotfrog.ca",
    "new zealand": "hotfrog.co.nz",
    "south africa": "hotfrog.co.za",
    "ireland": "hotfrog.ie",
    "germany": "hotfrog.de",
    "france": "hotfrog.fr",
    "spain": "hotfrog.es",
    "italy": "hotfrog.it",
    "netherlands": "hotfrog.nl",
    "brazil": "hotfrog.com.br",
    "mexico": "hotfrog.com.mx",
    "singapore": "hotfrog.sg",
    "malaysia": "hotfrog.com.my",
    "philippines": "hotfrog.ph",
}


class HotfrogScraper(BaseScraper):
    name = "Hotfrog"

    def search(self, keyword: str, city: str, country: str, limit: int = 50) -> List[Business]:
        domain = COUNTRY_DOMAIN.get(country.strip().lower())
        if not domain:
            raise ValueError(
                f"Hotfrog is not available for '{country}'. "
                "Supported: UK, US, India, Australia, UAE, Canada, NZ, South Africa, "
                "Ireland, Germany, France, Spain, Italy, Netherlands, Brazil, Mexico, "
                "Singapore, Malaysia, Philippines. For other countries use Bing Maps "
                "or OpenStreetMap."
            )
        base = f"https://www.{domain}/search/{quote(city.strip())}/{quote(keyword.strip())}"
        results, seen = [], set()
        for page in range(1, 9):  # paginate until limit or empty page
            url = base if page == 1 else f"{base}?page={page}"
            try:
                resp = requests.get(url, headers=HEADERS, timeout=25)
                resp.raise_for_status()
            except requests.RequestException as e:
                if page == 1:
                    raise RuntimeError(f"Hotfrog request failed ({domain}): {e}")
                break
            soup = BeautifulSoup(resp.text, "lxml")
            new_on_page = self._parse_cards(soup, domain, seen, results, limit)
            if len(results) >= limit or new_on_page == 0:
                break
        return self._fill_meta(results[:limit], keyword, city, country)

    def _parse_cards(self, soup, domain, seen, results, limit) -> int:
        new = 0
        for card in soup.select(".surface.entity"):
            name_el = card.select_one("h3.entity-title a")
            if not name_el:
                continue
            name = re.sub(r"\s+", " ", name_el.get_text()).strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            addr_el = card.select_one(".entity-address span")
            phone_el = card.select_one('a.has-icon--phone[href^="tel:"]')
            web_el = card.select_one("a.has-icon--website")
            cat_el = card.select_one(".entity-categories span span, .entity-categories")
            link = name_el.get("href", "")
            results.append(Business(
                name=name,
                category=re.sub(r"\s+", " ", cat_el.get_text()).strip() if cat_el else "",
                address=re.sub(r"\s+", " ", addr_el.get_text()).strip() if addr_el else "",
                phone=phone_el["href"].replace("tel:", "") if phone_el else "",
                website=web_el.get("href", "") if web_el else "",
                maps_url=f"https://www.{domain}{link}" if link.startswith("/") else link,
            ))
            new += 1
            if len(results) >= limit:
                break
        return new
