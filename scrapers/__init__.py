import os as _os

# Keep Playwright browsers inside the project — ~/.cache gets wiped on this
# system, which repeatedly breaks browser-based scrapers.
_os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH",
    _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), ".browsers"),
)

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
