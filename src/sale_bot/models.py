import re
from dataclasses import dataclass, field
from typing import Literal

ProviderName = Literal["daangn", "joongna", "bunjang"]
VALID_PROVIDERS = frozenset({"daangn", "joongna", "bunjang"})
MAX_DAANGN_REGIONS = 5


def split_daangn_regions(value: str | None) -> list[str]:
    if not value:
        return []
    regions: list[str] = []
    for part in re.split(r"[,;\n]+", value):
        region = part.strip()
        if region and region not in regions:
            regions.append(region)
    if len(regions) > MAX_DAANGN_REGIONS:
        raise ValueError(f"Daangn region limit reached ({MAX_DAANGN_REGIONS})")
    return regions


@dataclass(slots=True)
class Listing:
    provider: ProviderName
    external_id: str
    title: str
    price: int | None
    url: str
    location: str | None = None
    image_url: str | None = None


@dataclass(slots=True)
class Watch:
    name: str
    query: str
    min_price: int | None = None
    max_price: int | None = None
    exclude_keywords: list[str] = field(default_factory=list)
    providers: list[ProviderName] = field(default_factory=lambda: ["daangn", "joongna", "bunjang"])
    daangn_region: str | None = None

    @property
    def daangn_regions(self) -> list[str]:
        return split_daangn_regions(self.daangn_region)

    def matches(self, listing: Listing) -> bool:
        title = listing.title.casefold()
        if any(word.casefold() in title for word in self.exclude_keywords):
            return False
        if listing.price is None:
            return self.min_price is None and self.max_price is None
        if self.min_price is not None and listing.price < self.min_price:
            return False
        return self.max_price is None or listing.price <= self.max_price
