from dataclasses import dataclass
from pathlib import Path

import yaml

from .models import Watch


@dataclass(slots=True)
class Settings:
    poll_interval_seconds: int
    alert_on_first_seen: bool
    alert_on_price_increase: bool
    request_timeout_seconds: int
    watches: list[Watch]


def load_settings(path: str | Path) -> Settings:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    watches = [Watch(**item) for item in raw.get("watches", [])]
    if not watches:
        raise ValueError("config must contain at least one watch")
    return Settings(
        poll_interval_seconds=max(60, int(raw.get("poll_interval_seconds", 300))),
        alert_on_first_seen=bool(raw.get("alert_on_first_seen", True)),
        alert_on_price_increase=bool(raw.get("alert_on_price_increase", False)),
        request_timeout_seconds=int(raw.get("request_timeout_seconds", 20)),
        watches=watches,
    )
