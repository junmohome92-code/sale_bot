from dataclasses import dataclass
from pathlib import Path

import yaml

from .models import VALID_PROVIDERS, Watch, split_daangn_regions


@dataclass(slots=True)
class Settings:
    poll_interval_seconds: int
    request_timeout_seconds: int
    watches: list[Watch]


def load_settings(path: str | Path) -> Settings:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    raw = raw or {}
    watches = [Watch(**item) for item in raw.get("watches", [])]

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
        if watch.max_price is None or watch.max_price <= 0:
            raise ValueError(f"watch {watch.name}: max_price must be a positive integer")
        if watch.min_price is not None and watch.min_price < 0:
            raise ValueError(f"watch {watch.name}: min_price cannot be negative")
        if watch.min_price is not None and watch.min_price > watch.max_price:
            raise ValueError(f"watch {watch.name}: min_price cannot exceed max_price")

    return Settings(
        poll_interval_seconds=max(60, int(raw.get("poll_interval_seconds", 300))),
        request_timeout_seconds=max(5, int(raw.get("request_timeout_seconds", 20))),
        watches=watches,
    )
