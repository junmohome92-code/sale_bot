import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .models import Listing, Watch, split_daangn_regions

MAX_WATCH_SLOTS = 3


@dataclass(slots=True)
class Change:
    kind: str
    old_price: int | None
    new_price: int | None


def _encode_regions(regions: list[str]) -> str | None:
    return json.dumps(regions, ensure_ascii=False) if regions else None


def _decode_regions(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return split_daangn_regions(value)
    if isinstance(decoded, list):
        return split_daangn_regions([str(item) for item in decoded])
    return split_daangn_regions(value)


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS listings (
              provider TEXT NOT NULL,
              external_id TEXT NOT NULL,
              title TEXT NOT NULL,
              url TEXT NOT NULL,
              price INTEGER,
              location TEXT,
              first_seen_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              PRIMARY KEY (provider, external_id)
            );
            CREATE TABLE IF NOT EXISTS price_history (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              provider TEXT NOT NULL,
              external_id TEXT NOT NULL,
              price INTEGER,
              observed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scan_state (
              watch_name TEXT NOT NULL,
              provider TEXT NOT NULL,
              bootstrapped_at TEXT NOT NULL,
              PRIMARY KEY (watch_name, provider)
            );
            CREATE TABLE IF NOT EXISTS managed_watches (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              query TEXT NOT NULL,
              max_price INTEGER NOT NULL,
              exclude_keywords TEXT NOT NULL DEFAULT '[]',
              providers TEXT NOT NULL,
              daangn_region TEXT,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alert_receipts (
              watch_name TEXT NOT NULL,
              provider TEXT NOT NULL,
              external_id TEXT NOT NULL,
              alerted_at TEXT NOT NULL,
              PRIMARY KEY (watch_name, provider, external_id)
            );
            CREATE TABLE IF NOT EXISTS app_state (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            """
        )
        self.conn.commit()
        self._upgrade_alert_receipts_guard()

    def _row_to_watch(self, row: sqlite3.Row) -> Watch:
        return Watch(
            name=row["name"], query=row["query"], max_price=int(row["max_price"]),
            exclude_keywords=json.loads(row["exclude_keywords"]), providers=json.loads(row["providers"]),
            daangn_regions=_decode_regions(row["daangn_region"]),
        )

    def _upgrade_alert_receipts_guard(self) -> None:
        marker = "alert_receipts_upgrade_guard_v1"
        if self.conn.execute("SELECT 1 FROM app_state WHERE key=?", (marker,)).fetchone():
            return
        scan_count = int(self.conn.execute("SELECT COUNT(*) FROM scan_state").fetchone()[0])
        receipt_count = int(self.conn.execute("SELECT COUNT(*) FROM alert_receipts").fetchone()[0])
        if scan_count > 0 and receipt_count == 0:
            now = datetime.now(UTC).isoformat()
            for _, watch, _ in self.list_watches():
                for provider in watch.providers:
                    rows = self.conn.execute("SELECT * FROM listings WHERE provider=?", (provider,)).fetchall()
                    for row in rows:
                        listing = Listing(provider, str(row["external_id"]), str(row["title"]), row["price"], str(row["url"]), location=row["location"])
                        if watch.matches(listing):
                            self.conn.execute(
                                "INSERT OR IGNORE INTO alert_receipts(watch_name,provider,external_id,alerted_at) VALUES (?,?,?,?)",
                                (watch.name, provider, listing.external_id, now),
                            )
        self.conn.execute("INSERT OR REPLACE INTO app_state(key,value) VALUES (?,?)", (marker, "1"))
        self.conn.commit()

    def seed_watches(self, watches: list[Watch]) -> None:
        if self.conn.execute("SELECT 1 FROM app_state WHERE key='managed_watches_seeded'").fetchone():
            return
        now = datetime.now(UTC).isoformat()
        for watch in watches[:MAX_WATCH_SLOTS]:
            if watch.max_price is None:
                continue
            self.conn.execute(
                "INSERT OR IGNORE INTO managed_watches (name,query,max_price,exclude_keywords,providers,daangn_region,created_at) VALUES (?,?,?,?,?,?,?)",
                (watch.name, watch.query, watch.max_price, json.dumps(watch.exclude_keywords, ensure_ascii=False), json.dumps(watch.providers), _encode_regions(watch.daangn_regions), now),
            )
        self.conn.execute("INSERT OR REPLACE INTO app_state(key,value) VALUES ('managed_watches_seeded','1')")
        self.conn.commit()

    def list_watches(self, *, enabled_only: bool = False) -> list[tuple[int, Watch, bool]]:
        sql = "SELECT * FROM managed_watches" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY id"
        rows = self.conn.execute(sql).fetchall()
        return [(int(row["id"]), self._row_to_watch(row), bool(row["enabled"])) for row in rows]

    def add_watch(self, name: str, max_price: int, region: str | list[str] | None = None) -> int:
        name = name.strip()
        if not name:
            raise ValueError("watch name is required")
        if max_price <= 0:
            raise ValueError("max_price must be positive")
        if int(self.conn.execute("SELECT COUNT(*) FROM managed_watches").fetchone()[0]) >= MAX_WATCH_SLOTS:
            raise ValueError(f"watch slot limit reached ({MAX_WATCH_SLOTS})")
        if self.conn.execute("SELECT 1 FROM managed_watches WHERE name=?", (name,)).fetchone():
            raise ValueError("watch name already exists")
        now = datetime.now(UTC).isoformat()
        cur = self.conn.execute(
            "INSERT INTO managed_watches (name,query,max_price,exclude_keywords,providers,daangn_region,created_at) VALUES (?,?,?,'[]',?,?,?)",
            (name, name, max_price, json.dumps(["daangn", "joongna", "bunjang"]), _encode_regions(split_daangn_regions(region)), now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def delete_watch(self, watch_id: int) -> bool:
        row = self.conn.execute("SELECT name FROM managed_watches WHERE id=?", (watch_id,)).fetchone()
        if row is None:
            return False
        watch_name = str(row["name"])
        self.conn.execute("DELETE FROM managed_watches WHERE id=?", (watch_id,))
        self.conn.execute("DELETE FROM scan_state WHERE watch_name=?", (watch_name,))
        self.conn.execute("DELETE FROM alert_receipts WHERE watch_name=?", (watch_name,))
        self.conn.execute("DELETE FROM app_state WHERE key=?", (f"daangn_batch:{watch_name}",))
        self.conn.commit()
        return True

    def set_watch_enabled(self, watch_id: int, enabled: bool) -> bool:
        cur = self.conn.execute("UPDATE managed_watches SET enabled=? WHERE id=?", (int(enabled), watch_id)); self.conn.commit(); return cur.rowcount > 0

    def set_max_price(self, watch_id: int, max_price: int) -> bool:
        if max_price <= 0:
            raise ValueError("max_price must be positive")
        cur = self.conn.execute("UPDATE managed_watches SET max_price=? WHERE id=?", (max_price, watch_id)); self.conn.commit(); return cur.rowcount > 0

    def set_region(self, watch_id: int, region: str | list[str] | None) -> bool:
        cur = self.conn.execute("UPDATE managed_watches SET daangn_region=? WHERE id=?", (_encode_regions(split_daangn_regions(region)), watch_id)); self.conn.commit(); return cur.rowcount > 0

    def next_daangn_batch(self, watch_name: str, batch_count: int) -> int:
        batch_count = max(1, batch_count); key = f"daangn_batch:{watch_name}"
        row = self.conn.execute("SELECT value FROM app_state WHERE key=?", (key,)).fetchone(); current = int(row["value"]) if row else 0
        self.conn.execute("INSERT OR REPLACE INTO app_state(key,value) VALUES (?,?)", (key, str((current + 1) % batch_count))); self.conn.commit()
        return current % batch_count

    def update_exclude(self, watch_id: int, keyword: str, *, add: bool) -> bool:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("exclude keyword is required")
        row = self.conn.execute("SELECT exclude_keywords FROM managed_watches WHERE id=?", (watch_id,)).fetchone()
        if row is None:
            return False
        words = json.loads(row["exclude_keywords"])
        if add and keyword not in words: words.append(keyword)
        if not add: words = [word for word in words if word != keyword]
        self.conn.execute("UPDATE managed_watches SET exclude_keywords=? WHERE id=?", (json.dumps(words, ensure_ascii=False), watch_id)); self.conn.commit(); return True

    def has_alert_receipt(self, watch_name: str, listing: Listing) -> bool:
        return self.conn.execute("SELECT 1 FROM alert_receipts WHERE watch_name=? AND provider=? AND external_id=?", (watch_name, listing.provider, listing.external_id)).fetchone() is not None

    def reserve_alert(self, watch_name: str, listing: Listing) -> bool:
        now = datetime.now(UTC).isoformat()
        cur = self.conn.execute("INSERT OR IGNORE INTO alert_receipts(watch_name,provider,external_id,alerted_at) VALUES (?,?,?,?)", (watch_name, listing.provider, listing.external_id, now)); self.conn.commit(); return cur.rowcount > 0

    def observe(self, listing: Listing) -> Change:
        now = datetime.now(UTC).isoformat(); row = self.conn.execute("SELECT price FROM listings WHERE provider=? AND external_id=?", (listing.provider, listing.external_id)).fetchone()
        if row is None:
            self.conn.execute("INSERT INTO listings VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (listing.provider, listing.external_id, listing.title, listing.url, listing.price, listing.location, now, now))
            self.conn.execute("INSERT INTO price_history(provider,external_id,price,observed_at) VALUES (?,?,?,?)", (listing.provider, listing.external_id, listing.price, now)); self.conn.commit(); return Change("new", None, listing.price)
        old_price = row["price"]
        self.conn.execute("UPDATE listings SET title=?,url=?,price=?,location=?,last_seen_at=? WHERE provider=? AND external_id=?", (listing.title, listing.url, listing.price, listing.location, now, listing.provider, listing.external_id))
        kind = "same"
        if old_price != listing.price:
            self.conn.execute("INSERT INTO price_history(provider,external_id,price,observed_at) VALUES (?,?,?,?)", (listing.provider, listing.external_id, listing.price, now))
            kind = "price_down" if old_price is not None and listing.price is not None and listing.price < old_price else "price_up" if old_price is not None and listing.price is not None else "price_changed"
        self.conn.commit(); return Change(kind, old_price, listing.price)

    def is_bootstrapped(self, watch_name: str, provider: str) -> bool:
        return self.conn.execute("SELECT 1 FROM scan_state WHERE watch_name=? AND provider=?", (watch_name, provider)).fetchone() is not None

    def mark_bootstrapped(self, watch_name: str, provider: str) -> None:
        self.conn.execute("INSERT OR IGNORE INTO scan_state(watch_name,provider,bootstrapped_at) VALUES (?,?,?)", (watch_name, provider, datetime.now(UTC).isoformat())); self.conn.commit()

    def close(self) -> None:
        self.conn.close()
