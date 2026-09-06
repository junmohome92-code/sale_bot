from collections import OrderedDict
from time import monotonic

_MISSING = object()


class BoundedTTLCache[K, V]:
    """Small in-memory TTL+LRU cache with a hard item cap."""

    def __init__(self, maxsize: int, ttl_seconds: float):
        self.maxsize = max(1, int(maxsize))
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self._items: OrderedDict[K, tuple[float, V]] = OrderedDict()

    def get(self, key: K, default=None):
        item = self._items.get(key)
        if item is None:
            return default
        created_at, value = item
        if monotonic() - created_at >= self.ttl_seconds:
            self._items.pop(key, None)
            return default
        self._items.move_to_end(key)
        return value

    def __contains__(self, key: K) -> bool:
        return self.get(key, _MISSING) is not _MISSING

    def __getitem__(self, key: K) -> V:
        value = self.get(key, _MISSING)
        if value is _MISSING:
            raise KeyError(key)
        return value

    def __setitem__(self, key: K, value: V) -> None:
        self.set(key, value)

    def set(self, key: K, value: V) -> None:
        self.cleanup()
        self._items[key] = (monotonic(), value)
        self._items.move_to_end(key)
        while len(self._items) > self.maxsize:
            self._items.popitem(last=False)

    def cleanup(self) -> None:
        now = monotonic()
        expired = [
            key
            for key, (created_at, _) in self._items.items()
            if now - created_at >= self.ttl_seconds
        ]
        for key in expired:
            self._items.pop(key, None)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        self.cleanup()
        return len(self._items)
