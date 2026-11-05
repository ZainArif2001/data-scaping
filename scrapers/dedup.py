"""Merge + deduplicate results from multiple scrapers."""
import re
from typing import List
from urllib.parse import urlparse

from .base import Business

_STRIP_WORDS = re.compile(r"\b(ltd|limited|llc|inc|gmbh|plc|the|uk|co|company)\b", re.I)


def _norm_name(name: str) -> str:
    n = _STRIP_WORDS.sub("", name.lower())
    return re.sub(r"[^a-z0-9]", "", n)


def _domain(url: str) -> str:
    try:
        d = urlparse(url if "://" in url else "http://" + url).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


SYNONYMS = {
    "gym": ["gym", "fitness", "health club", "leisure centre", "sports centre",
            "sports center", "fitness centre", "fitness center", "workout",
            "crossfit", "yoga", "pilates", "boxing"],
    "restaurant": ["restaurant", "cafe", "diner", "eatery", "food", "pizza",
                   "takeaway", "takeout", "bistro", "grill", "kitchen", "curry"],
    "dentist": ["dental", "dentist", "orthodont"],
    "doctor": ["doctor", "clinic", "medical", "gp surgery", "physician", "health centre"],
    "hotel": ["hotel", "guest house", "inn", "lodge", "b&b", "bed and breakfast"],
    "salon": ["salon", "hair", "barber", "beauty", "nail", "spa"],
    "barber": ["barber", "hair", "salon"],
    "plumber": ["plumb", "heating", "boiler", "gas engineer"],
    "electrician": ["electric"],
    "pharmacy": ["pharmacy", "chemist", "drugstore"],
    "supermarket": ["supermarket", "grocery", "convenience", "market", "store"],
    "school": ["school", "academy", "college", "nursery", "kindergarten"],
    "lawyer": ["law", "solicitor", "attorney", "legal"],
    "accountant": ["account", "tax", "bookkeep"],
    "vet": ["vet", "animal", "pet"],
    "cleaner": ["clean", "maid", "janitor"],
    "builder": ["build", "construct", "contractor", "renovat"],
    "mechanic": ["garage", "mechanic", "auto", "car repair", "mot", "tyre", "tire"],
    "estate agent": ["estate", "property", "letting", "realty", "real estate"],
}


def relevant(biz: Business, keyword: str) -> bool:
    """Keep the business if it looks related to the searched keyword."""
    hay = f"{biz.name} {biz.category}".lower()
    kw = keyword.strip().lower()
    if not kw:
        return True
    terms = {kw, kw.rstrip("s"), kw + "s"}
    terms |= set(SYNONYMS.get(kw, []))
    terms |= set(SYNONYMS.get(kw.rstrip("s"), []))
    return any(t and t in hay for t in terms)


def filter_relevant(results: List[Business], keyword: str) -> List[Business]:
    """Drop clearly irrelevant results; never return empty if we had data."""
    kept = [b for b in results if relevant(b, keyword)]
    return kept if kept else results


def merge_results(*result_lists: List[Business]) -> List[Business]:
    """Merge lists; a business is a duplicate if normalized name or
    website domain already seen. First occurrence wins."""
    out, names, domains = [], set(), set()
    for lst in result_lists:
        for b in lst:
            nkey = _norm_name(b.name)
            dom = _domain(b.website) if b.website else ""
            if nkey and nkey in names:
                continue
            if dom and dom in domains:
                continue
            names.add(nkey)
            if dom:
                domains.add(dom)
            out.append(b)
    return out
