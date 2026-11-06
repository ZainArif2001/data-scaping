import os as _os
import subprocess as _sp
from pathlib import Path as _Path

# Keep Playwright browsers inside the project — ~/.cache gets wiped on this
# system, which repeatedly breaks browser-based scrapers.
_os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH",
    _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), ".browsers"),
)

# Fresh deploys (e.g. Streamlit Cloud) have no browser binaries — install once.
if not list(_Path(_os.environ["PLAYWRIGHT_BROWSERS_PATH"]).glob("chromium-*/chrome-linux/chrome")):
    try:
        _sp.run(["playwright", "install", "chromium"], check=True)
    except Exception:
        pass

from .osm import OSMScraper
from .yellowpages import YellowPagesScraper
from .google_maps import GoogleMapsScraper
from .bing_maps import BingMapsScraper
from .hotfrog import HotfrogScraper

SCRAPERS = {
    OSMScraper.name: OSMScraper,
    BingMapsScraper.name: BingMapsScraper,
    HotfrogScraper.name: HotfrogScraper,
    "Yellow Pages": YellowPagesScraper,
    GoogleMapsScraper.name: GoogleMapsScraper,
}
