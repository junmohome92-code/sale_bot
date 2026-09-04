from dataclasses import dataclass
from pathlib import Path

import yaml

from .models import VALID_PROVIDERS, Watch, split_daangn_regions


@dataclass(slots=True)
class Settings:
    poll_interval_seconds: int
    alert_on_first_seen: bool
    alert_on_price_increase: bool
    bootstrap_silently: bool
    request_timeout_seconds: int
    daangn_full_region_batches: int
    watches: list[Watch]


def load_settings(path: str | Path) -> Settings:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    watches = [Watch(**item) for item in raw.get("watches", [])]
    if not watches:
        raise ValueError("config must contain at least one watch")

    names = [watch.name for watch in watches]
    if len(names) != len(set(names)):
        raise ValueError("watch names must be unique")

    for watch in watches:
        if not watch.name.strip() or not watch.query.strip():
            raise ValueError("every watch requires non-empty name and query")
        invalid = set(watch.providers) - VALID_PROVIDERS
        if invalid:
            raise ValueError(f"unknown provider(s) in {watch.name}: {sorted(invalid)}")
        if not watch.providers:
            raise ValueError(f"watch {watch.name} must contain at least one provider")
        split_daangn_regions(watch.daangn_regions)
        if (
            watch.min_price is not None
            and watch.max_price is not None
            and watch.min_price > watch.max_price
        ):
            raise ValueError(f"watch {watch.name}: min_price cannot exceed max_price")

    return Settings(
        poll_interval_seconds=max(60, int(raw.get("poll_interval_seconds", 300))),
        alert_on_first_seen=bool(raw.get("alert_on_first_seen", True)),
        alert_on_price_increase=bool(raw.get("alert_on_price_increase", False)),
        bootstrap_silently=bool(raw.get("bootstrap_silently", True)),
        request_timeout_seconds=max(5, int(raw.get("request_timeout_seconds", 20))),
        daangn_full_region_batches=max(1, min(10, int(raw.get("daangn_full_region_batches", 5)))),
        watches=watches,
    )
