"""Split a city's bounding box into a grid of search points.

Deep-sweep mode: instead of one city-wide query (which returns ~10-30
results), we query maps at each cell centre — every cell returns a
different local set, merged+deduped for 10-20x coverage.
"""
import math
import requests
from typing import List, Optional, Tuple

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "BizDataScraper/1.0"}


def city_bbox(city: str, country: str) -> Optional[Tuple[float, float, float, float]]:
    """Return (south, north, west, east) bounds for the city."""
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": f"{city}, {country}", "format": "json", "limit": 3},
            headers=HEADERS, timeout=20,
        )
        resp.raise_for_status()
        for r in resp.json():
            if r.get("boundingbox") and r.get("osm_type") == "relation":
                s, n, w, e = (float(x) for x in r["boundingbox"])
                return s, n, w, e
        for r in resp.json():
            if r.get("boundingbox"):
                s, n, w, e = (float(x) for x in r["boundingbox"])
                return s, n, w, e
    except requests.RequestException:
        pass
    return None


def _populated_bbox(city: str, country: str,
                    bb: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    """Tighten the admin bbox to where people actually live, using the
    country's GeoNames locality file (skips desert/water/rural fringe)."""
    import json
    import os
    iso_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "country_iso.json")
    try:
        iso = json.load(open(iso_path)).get(country)
    except OSError:
        iso = None
    if not iso:
        return bb
    geo_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "geonames", f"{iso}.json")
    try:
        places = json.load(open(geo_file))
    except OSError:
        return bb
    s, n, w, e = bb
    inside = [(p["lat"], p["lon"]) for p in places
              if s <= p["lat"] <= n and w <= p["lon"] <= e]
    if len(inside) < 10:
        return bb
    lats = sorted(x[0] for x in inside)
    lons = sorted(x[1] for x in inside)
    # trim extreme 3% outliers -> dense core
    k = max(1, len(inside) // 33)
    return (lats[k], lats[-k], lons[k], lons[-k])


def grid_points(city: str, country: str, max_cells: int = 30,
                min_cell_km: float = 2.0) -> List[Tuple[float, float]]:
    """Cell centres covering the city. Fewer/ bigger cells for small cities."""
    bb = city_bbox(city, country)
    if not bb:
        return []
    bb = _populated_bbox(city, country, bb)
    s, n, w, e = bb
    lat_km = (n - s) * 111
    lon_km = (e - w) * 111 * math.cos(math.radians((s + n) / 2))
    if lat_km < 1 or lon_km < 1:
        return [((s + n) / 2, (w + e) / 2)]

    aspect = max(lon_km / lat_km, 1e-6)
    cols = max(1, round(math.sqrt(max_cells * aspect)))
    rows = max(1, round(math.sqrt(max_cells / aspect)))
    # shrink so cells aren't smaller than min_cell_km
    while cols > 1 and lon_km / cols < min_cell_km:
        cols -= 1
    while rows > 1 and lat_km / rows < min_cell_km:
        rows -= 1

    pts = []
    for i in range(rows):
        for j in range(cols):
            lat = s + (i + 0.5) * (n - s) / rows
            lon = w + (j + 0.5) * (e - w) / cols
            pts.append((round(lat, 5), round(lon, 5)))
    return pts
