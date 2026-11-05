"""Area/district discovery for a city.

- Local GeoNames index (data/subareas.json) — neighbourhoods & districts
  inside the city boundary. No network needed, can't be rate-limited.
- UK additionally -> postal districts (CV1, E2...) via free postcodes.io.
"""
import json
import math
import os
import time
import requests
from typing import List, Optional

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_URL = "https://photon.komoot.io/api/"
POSTCODES_URL = "https://api.postcodes.io/outcodes"
HEADERS = {"User-Agent": "BizDataScraper/1.0"}

UK_NAMES = {"united kingdom", "uk", "england", "scotland", "wales",
            "northern ireland", "great britain"}

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_SUBAREAS_PATH = os.path.join(_DATA_DIR, "subareas.json")
_ISO_PATH = os.path.join(_DATA_DIR, "country_iso.json")
_GEONAMES_DIR = os.path.join(_DATA_DIR, "geonames")
_subareas_cache = None
_iso_cache = None


def _load_json(path, cache_holder):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


def _load_subareas() -> dict:
    global _subareas_cache
    if _subareas_cache is None:
        _subareas_cache = _load_json(_SUBAREAS_PATH, None)
    return _subareas_cache


def _iso_for(country: str) -> Optional[str]:
    global _iso_cache
    if _iso_cache is None:
        _iso_cache = _load_json(_ISO_PATH, None)
    return _iso_cache.get(country)


def _country_places(country: str) -> List[dict]:
    """All populated places for a country (PPL* entries), cached on disk.
    Downloads the country's GeoNames file once (~1-25 MB)."""
    iso = _iso_for(country)
    if not iso:
        return []
    os.makedirs(_GEONAMES_DIR, exist_ok=True)
    cache = os.path.join(_GEONAMES_DIR, f"{iso}.json")
    if os.path.exists(cache):
        return _load_json(cache, None)
    import io
    import zipfile
    try:
        resp = requests.get(
            f"https://download.geonames.org/export/dump/{iso}.zip", timeout=60
        )
        resp.raise_for_status()
        places = []
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            with z.open(f"{iso}.txt") as fh:
                for raw in io.TextIOWrapper(fh, encoding="utf-8"):
                    f = raw.rstrip("\n").split("\t")
                    if len(f) < 15 or f[6] != "P" or not f[7].startswith("PPL"):
                        continue
                    try:
                        places.append({
                            "n": f[2],
                            "lat": round(float(f[4]), 4),
                            "lon": round(float(f[5]), 4),
                        })
                    except ValueError:
                        continue
        with open(cache, "w", encoding="utf-8") as fh:
            json.dump(places, fh, ensure_ascii=False)
        return places
    except Exception:
        return []


def _geocode(city: str, country: str) -> Optional[dict]:
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": f"{city}, {country}", "format": "json", "limit": 3},
            headers=HEADERS, timeout=20,
        )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            return None
        for r in results:
            if r.get("osm_type") == "relation":
                return r
        return results[0]
    except requests.RequestException:
        return None


def _bbox_radius_km(geo: dict, lat: float) -> float:
    bb = geo.get("boundingbox")  # [south, north, west, east]
    if not bb:
        return 15.0
    dlat = abs(float(bb[1]) - float(bb[0])) * 111
    dlon = abs(float(bb[3]) - float(bb[2])) * 111 * math.cos(math.radians(lat))
    return max(12.0, min(40.0, (dlat + dlon) / 4 + 5))


def _uk_outcodes(lat: float, lon: float, radius_km: float) -> List[str]:
    try:
        resp = requests.get(
            POSTCODES_URL,
            params={"lat": lat, "lon": lon, "radius": int(radius_km * 1000), "limit": 99},
            timeout=15,
        )
        resp.raise_for_status()
        return [o["outcode"] for o in resp.json().get("result") or []]
    except requests.RequestException:
        return []


def _bbox_entries(entries: List[dict], geo: dict, pad: float = 1.2) -> List[str]:
    """Names inside the city's bounding box (slightly padded)."""
    bb = geo.get("boundingbox")
    if not bb or not entries:
        return []
    s, n, w, e = (float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3]))
    hpad, wpad = (n - s) * (pad - 1) / 2, (e - w) * (pad - 1) / 2
    s, n, w, e = s - hpad, n + hpad, w - wpad, e + wpad
    out = [x["n"] for x in entries if s <= x["lat"] <= n and w <= x["lon"] <= e]
    return sorted(set(out), key=str.lower)


def _local_subareas(geo: dict, country: str) -> List[str]:
    return _bbox_entries(_load_subareas().get(country, []), geo)


def _country_subareas(geo: dict, country: str) -> List[str]:
    return _bbox_entries(_country_places(country), geo)


def _photon_subareas(city: str, geo: dict) -> List[str]:
    """Gentle supplement: sequential Photon queries (rate-limit safe).
    Finds areas whose names contain the city name (common in PK/IN/etc)."""
    out, seen = [], set()
    bb = geo.get("boundingbox")
    bbox = f"{bb[2]},{bb[0]},{bb[3]},{bb[1]}" if bb else None
    for ptype in ("place:suburb", "place:neighbourhood", "place:quarter", "place:district"):
        params = [("q", city), ("limit", "50"), ("osm_tag", ptype)]
        if bbox:
            params.append(("bbox", bbox))
        try:
            resp = requests.get(PHOTON_URL, params=params, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            for f in resp.json().get("features", []):
                name = (f.get("properties", {}).get("name") or "").strip()
                if name and name.lower() not in seen:
                    seen.add(name.lower())
                    out.append(name)
        except requests.RequestException:
            break  # Photon unreachable/rate-limited — stop, keep what we have
        time.sleep(0.5)
    return out


def get_areas(city: str, country: str) -> List[str]:
    """Return area names/postcodes for a city, sorted (empty list on failure)."""
    geo = _geocode(city, country)
    if not geo:
        return []
    areas = _local_subareas(geo, country)
    if len(areas) < 15:
        # thin local index -> use the country's full GeoNames file
        areas = sorted(set(areas) | set(_country_subareas(geo, country)), key=str.lower)
    if country.strip().lower() in UK_NAMES:
        lat, lon = float(geo["lat"]), float(geo["lon"])
        areas = _uk_outcodes(lat, lon, _bbox_radius_km(geo, lat)) + areas
    areas += _photon_subareas(city, geo)
    return sorted(set(areas), key=str.lower)
