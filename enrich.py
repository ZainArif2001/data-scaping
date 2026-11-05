"""Enrichment: visit each business website and extract emails + social links."""
import re
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
from urllib.parse import urljoin, urlparse

from scrapers.base import Business

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}
TIMEOUT = 12

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
BAD_EMAIL_RE = re.compile(
    r"(\.png|\.jpg|\.jpeg|\.gif|\.webp|\.svg|@example\.|@sentry|@wixpress|@2x\.|@domain)",
    re.I,
)
SOCIAL_DOMAINS = [
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "linkedin.com", "youtube.com", "tiktok.com",
]
BAD_SOCIAL_RE = re.compile(r"(share\.php|sharer|/share\?|intent/tweet|plugins/|/tr\?)", re.I)


def _fetch(url: str) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if "text/html" not in resp.headers.get("Content-Type", "text/html"):
            return ""
        return resp.text[:500_000]
    except requests.RequestException:
        return ""


def _extract(html: str, base_url: str):
    soup = BeautifulSoup(html, "lxml")
    text_emails = {e.lower() for e in EMAIL_RE.findall(soup.get_text(" "))}
    mailto_emails, socials, contact_pages = set(), set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower()
        if low.startswith("mailto:"):
            mailto_emails.add(href[7:].split("?")[0].lower())
        elif any(d in low for d in SOCIAL_DOMAINS) and not BAD_SOCIAL_RE.search(low):
            socials.add(href.split("?")[0].rstrip("/"))
        elif "contact" in low and len(contact_pages) < 2:
            contact_pages.append(urljoin(base_url, href))
    emails = {e for e in (text_emails | mailto_emails) if not BAD_EMAIL_RE.search(e)}
    return emails, socials, contact_pages


def enrich_one(biz: Business) -> Business:
    if not biz.website or not biz.website.startswith("http"):
        return biz
    html = _fetch(biz.website)
    if not html:
        return biz
    emails, socials, contact_pages = _extract(html, biz.website)
    # No email on homepage -> try the contact page
    if not emails and contact_pages:
        html2 = _fetch(contact_pages[0])
        if html2:
            e2, s2, _ = _extract(html2, contact_pages[0])
            emails |= e2
            socials |= s2
    if emails and not biz.email:
        biz.email = "; ".join(sorted(emails)[:3])
    if socials:
        existing = set(filter(None, (s.strip() for s in biz.social_media.split(";"))))
        biz.social_media = "; ".join(sorted(existing | socials))
    return biz


def enrich_all(results: List[Business], max_workers: int = 8, progress_cb=None) -> List[Business]:
    targets = [b for b in results if b.website]
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(enrich_one, b): b for b in targets}
        for fut in as_completed(futures):
            done += 1
            if progress_cb:
                progress_cb(done, len(targets))
    return results
