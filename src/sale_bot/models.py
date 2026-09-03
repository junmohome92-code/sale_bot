from dataclasses import dataclass, field
from typing import Literal

ProviderName = Literal["daangn", "joongna", "bunjang"]


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

    def matches(self, listing: Listing) -> bool:
        title = listing.title.casefold()
        if any(word.casefold() in title for word in self.exclude_keywords):
            return False
        if listing.price is not None:
            if self.min_price is not None and listing.price < self.min_price:
                return False
            if self.max_price is not None and listing.price > self.max_price:
                return False
        return True
