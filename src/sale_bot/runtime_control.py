import asyncio

from .storage import Store

PROVIDER_NAMES = ("daangn", "joongna", "bunjang")
ALLOWED_POLL_INTERVALS = (300, 600, 900, 1800)
_SCAN_EVENTS = {name: asyncio.Event() for name in PROVIDER_NAMES}


def request_scan(provider: str | None = None) -> None:
    names = (provider,) if provider else PROVIDER_NAMES
    for name in names:
        event = _SCAN_EVENTS.get(name)
        if event is not None:
            event.set()


async def wait_for_scan_or_timeout(provider: str, timeout_seconds: float) -> bool:
    event = _SCAN_EVENTS[provider]
    if event.is_set():
        event.clear()
        return True
    if timeout_seconds <= 0:
        return False
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
    except TimeoutError:
        return False
    event.clear()
    return True


def get_poll_interval(store: Store, default: int = 300) -> int:
    row = store.conn.execute(
        "SELECT value FROM runtime_state WHERE key='poll_interval_seconds'"
    ).fetchone()
    if row is None:
        return max(300, int(default))
    try:
        value = int(row["value"])
    except (TypeError, ValueError):
        return max(300, int(default))
    return value if value in ALLOWED_POLL_INTERVALS else max(300, int(default))


def set_poll_interval(store: Store, seconds: int) -> None:
    if seconds not in ALLOWED_POLL_INTERVALS:
        raise ValueError("unsupported poll interval")
    store.conn.execute(
        "INSERT OR REPLACE INTO runtime_state(key,value) VALUES ('poll_interval_seconds',?)",
        (str(seconds),),
    )
    store.conn.commit()


def set_provider_running(store: Store, provider: str, started_at: str | None) -> None:
    key = f"provider_running:{provider}"
    if started_at is None:
        store.conn.execute("DELETE FROM runtime_state WHERE key=?", (key,))
    else:
        store.conn.execute(
            "INSERT OR REPLACE INTO runtime_state(key,value) VALUES (?,?)",
            (key, started_at),
        )
    store.conn.commit()


def provider_running_since(store: Store, provider: str) -> str | None:
    row = store.conn.execute(
        "SELECT value FROM runtime_state WHERE key=?",
        (f"provider_running:{provider}",),
    ).fetchone()
    return str(row["value"]) if row is not None else None


def clear_running_flags(store: Store) -> None:
    store.conn.execute("DELETE FROM runtime_state WHERE key LIKE 'provider_running:%'")
    store.conn.commit()
