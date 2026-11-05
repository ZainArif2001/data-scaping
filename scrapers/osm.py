"""OpenStreetMap scraper.

Primary:  Photon geocoder (photon.komoot.io) — fast, free, no key.
Fallback: Overpass API — richer tags (phone/website/email) but often
          rate-limited or blocked on some networks.

Note: OSM has no ratings/reviews.
"""
import re
import requests
from typing import List, Optional
from urllib.parse import urlencode

from .base import BaseScraper, Business

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_URL = "https://photon.komoot.io/api/"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
HEADERS = {"User-Agent": "BizDataScraper/1.0 (local research tool)"}

BIZ_KEYS = ["amenity", "shop", "leisure", "office", "craft", "tourism", "healthcare", "club"]


def _geocode(city: str, country: str) -> Optional[dict]:
    resp = requests.get(
        NOMINATIM_URL,
        params={"q": f"{city}, {country}", "format": "json", "limit": 5},
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        return None
    # prefer a relation (administrative boundary); else first hit with a bbox
    for r in results:
        if r.get("osm_type") == "relation" and r.get("boundingbox"):
            return r
    return results[0]


def _area_id(geo: dict) -> Optional[int]:
    if geo.get("osm_type") == "relation":
        return 3600000000 + int(geo["osm_id"])
    if geo.get("osm_type") == "way":
        return 2400000000 + int(geo["osm_id"])
    return None


# ---------------- Photon (primary) ----------------

def _search_photon(keyword: str, city: str, country: str, geo: dict, limit: int) -> List[Business]:
    params = [("q", f"{keyword} {city}"), ("limit", min(limit * 3, 100))]
    # bounding box from geocoding: [south, north, west, east] -> lon/lat order
    bb = geo.get("boundingbox")
    if bb:
        params.append(("bbox", f"{bb[2]},{bb[0]},{bb[3]},{bb[1]}"))
    for k in ("amenity", "shop", "leisure", "office", "craft", "tourism"):
        params.append(("osm_tag", k))

    resp = requests.get(PHOTON_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    kw = keyword.strip().lower()
    results, seen = [], set()
    for f in resp.json().get("features", []):
        p = f.get("properties", {})
        name = (p.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        # relevance filter: keyword in name or in the osm tag value
        osm_val = str(p.get("osm_value") or "").lower()
        if kw not in name.lower() and kw not in osm_val:
            continue
        seen.add(name.lower())
        street = " ".join(filter(None, [str(p.get("housenumber") or ""), p.get("street") or ""])).strip()
        address = ", ".join(filter(None, [street, p.get("district") or p.get("city"),
                                          p.get("postcode"), p.get("country")]))
        osm_type = p.get("osm_type", "N")
        prefix = {"N": "node", "W": "way", "R": "relation"}.get(osm_type, "node")
        results.append(Business(
            name=name,
            address=address,
            category=str(p.get("osm_value") or ""),
            maps_url=f"https://www.openstreetmap.org/{prefix}/{p.get('osm_id')}",
        ))
        if len(results) >= limit:
            break
    return results


# ---------------- Overpass (fallback for richer tags) ----------------

def _addr(tags: dict) -> str:
    parts = [
        " ".join(filter(None, [tags.get("addr:housenumber", ""), tags.get("addr:street", "")])).strip(),
        tags.get("addr:city", ""),
        tags.get("addr:postcode", ""),
        tags.get("addr:country", ""),
    ]
    return ", ".join(p for p in parts if p)


def _socials(tags: dict) -> str:
    links = []
    for key in ("contact:facebook", "facebook", "contact:instagram", "instagram",
                "contact:twitter", "twitter", "contact:youtube", "youtube",
                "contact:linkedin", "linkedin"):
        val = tags.get(key)
        if not val:
            continue
        if val.startswith("http"):
            links.append(val)
        else:
            site = key.split(":")[-1]
            links.append(f"https://{site}.com/{val.lstrip('@')}")
    return "; ".join(dict.fromkeys(links))


def _maps_url(el: dict) -> str:
    t = el.get("type", "node")
    return f"https://www.openstreetmap.org/{t}/{el['id']}"


def _search_overpass(keyword: str, area_id: int, limit: int) -> List[Business]:
    kw = re.escape(keyword.strip())
    keys = "|".join(BIZ_KEYS)
    query = f"""
[out:json][timeout:30];
area({area_id})->.a;
(
  nwr["name"~"{kw}",i](area.a);
  nwr[~"^({keys})$"~"^{kw}",i](area.a);
);
out center tags {limit * 2};
"""
    last_err = None
    for url in OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
            break
        except requests.RequestException as e:
            last_err = e
    else:
        raise RuntimeError(f"Overpass unavailable: {last_err}")

    results, seen = [], set()
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name", "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        results.append(Business(
            name=name,
            address=_addr(tags),
            phone=tags.get("phone") or tags.get("contact:phone", ""),
            website=tags.get("website") or tags.get("contact:website") or tags.get("url", ""),
            email=tags.get("email") or tags.get("contact:email", ""),
            social_media=_socials(tags),
            maps_url=_maps_url(el),
        ))
        if len(results) >= limit:
            break
    return results


_OVERPASS_DOWN = False  # set once Overpass fails; skip it for the session


class OSMScraper(BaseScraper):
    name = "OpenStreetMap"

    def search(self, keyword: str, city: str, country: str, limit: int = 50) -> List[Business]:
        geo = _geocode(city, country)
        if not geo:
            raise ValueError(f"City not found on OpenStreetMap: {city}, {country}")

        # Try Overpass first (richer data), fall back to Photon
        global _OVERPASS_DOWN
        area = _area_id(geo)
        if area and not _OVERPASS_DOWN:
            try:
                results = _search_overpass(keyword, area, limit)
                if results:
                    return self._fill_meta(results, keyword, city, country)
            except Exception:
                _OVERPASS_DOWN = True

        results = _search_photon(keyword, city, country, geo, limit)
        return self._fill_meta(results, keyword, city, country)
