import re
from dataclasses import dataclass, field
from typing import Literal

ProviderName = Literal["daangn", "joongna", "bunjang"]
VALID_PROVIDERS = frozenset({"daangn", "joongna", "bunjang"})
MAX_DAANGN_REGION_SPECS = 10


def split_daangn_regions(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if not value:
        return []
    raw_parts: list[str] = []
    if isinstance(value, str):
        raw_parts.extend(re.split(r"[,;\n]+", value))
    else:
        for item in value:
            raw_parts.extend(re.split(r"[,;\n]+", str(item)))

    regions: list[str] = []
    for part in raw_parts:
        region = part.strip()
        if region and region not in regions:
            regions.append(region)
    if len(regions) > MAX_DAANGN_REGION_SPECS:
        raise ValueError(f"Daangn region limit reached ({MAX_DAANGN_REGION_SPECS})")
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
    ignore_price_at_or_below: int = 0
    exclude_keywords: list[str] = field(default_factory=list)
    providers: list[ProviderName] = field(default_factory=lambda: ["daangn", "joongna", "bunjang"])
    daangn_region: str | None = None
    daangn_regions: list[str] = field(default_factory=list)
    # Legacy diagnostic-only fields. Runtime scheduling no longer exposes batch tuning.
    daangn_batch_index: int = 0
    daangn_batch_count: int = 5

    def __post_init__(self) -> None:
        if self.ignore_price_at_or_below < 0:
            raise ValueError("ignore_price_at_or_below cannot be negative")
        merged = split_daangn_regions(self.daangn_regions)
        for region in split_daangn_regions(self.daangn_region):
            if region not in merged:
                merged.append(region)
        if len(merged) > MAX_DAANGN_REGION_SPECS:
            raise ValueError(f"Daangn region limit reached ({MAX_DAANGN_REGION_SPECS})")
        self.daangn_regions = merged

    def matches(self, listing: Listing) -> bool:
        title = listing.title.casefold()
        if any(word.casefold() in title for word in self.exclude_keywords):
            return False
        if listing.price is None:
            return self.min_price is None and self.max_price is None
        if self.ignore_price_at_or_below and listing.price <= self.ignore_price_at_or_below:
            return False
        if self.min_price is not None and listing.price < self.min_price:
            return False
        return self.max_price is None or listing.price <= self.max_price
