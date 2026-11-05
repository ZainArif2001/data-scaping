"""Shared data structures for all scrapers."""
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Business:
    name: str = ""
    address: str = ""
    phone: str = ""
    website: str = ""
    email: str = ""
    rating: Optional[float] = None
    reviews: Optional[int] = None
    social_media: str = ""
    category: str = ""
    source: str = ""
    maps_url: str = ""
    keyword: str = ""
    city: str = ""
    country: str = ""

    def to_dict(self):
        return asdict(self)


class BaseScraper:
    name = "base"

    def search(self, keyword: str, city: str, country: str, limit: int = 50) -> List[Business]:
        raise NotImplementedError

    def _fill_meta(self, results: List[Business], keyword: str, city: str, country: str) -> List[Business]:
        for r in results:
            r.source = self.name
            r.keyword = keyword
            r.city = city
            r.country = country
        return results
