import re

from .models import Listing, Watch

_CITY_SUFFIXES = (
    "특별자치시",
    "특별시",
    "광역시",
    "자치시",
    "시",
)


def _geo_key(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-z가-힣]+", "", text).casefold()
    for suffix in _CITY_SUFFIXES:
        suffix_key = re.sub(r"[^0-9A-Za-z가-힣]+", "", suffix).casefold()
        if value.endswith(suffix_key) and len(value) > len(suffix_key):
            return value[: -len(suffix_key)]
    return value


def city_labels_from_regions(regions: list[str]) -> list[str]:
    """Extract city-level labels from validated Daangn region strings."""
    labels: list[str] = []
    for region in regions:
        tokens = [token for token in re.split(r"[\s>]+", region) if token and token != "전체"]
        city = next((token for token in tokens if token.endswith(_CITY_SUFFIXES)), None)
        if city and city not in labels:
            labels.append(city)
    return labels


def city_keys_from_watch(watch: Watch) -> list[str]:
    keys: list[str] = []
    for label in city_labels_from_regions(watch.daangn_regions):
        key = _geo_key(label)
        if key and key not in keys:
            keys.append(key)
    return keys


def market_city_text(watch: Watch) -> str:
    labels = city_labels_from_regions(watch.daangn_regions)
    return ", ".join(labels) if labels else "전국"


def listing_matches_market_city(watch: Watch, listing: Listing) -> bool:
    """Daangn keeps detailed regions; Joongna/Bunjang are city-only."""
    if listing.provider == "daangn":
        return True
    city_keys = city_keys_from_watch(watch)
    if not city_keys:
        return True
    if not listing.location:
        return False
    location_key = _geo_key(listing.location)
    return any(key in location_key for key in city_keys)
