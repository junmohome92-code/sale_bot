import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .models import Listing, Watch


@dataclass(slots=True)
class Change:
    kind: str
    old_price: int | None
    new_price: int | None


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
            """
        )
        self.conn.commit()

    def seed_watches(self, watches: list[Watch]) -> None:
        if self.conn.execute("SELECT 1 FROM managed_watches LIMIT 1").fetchone():
            return
        now = datetime.now(UTC).isoformat()
        for watch in watches:
            if watch.max_price is None:
                continue
            self.conn.execute(
                """INSERT OR IGNORE INTO managed_watches
                (name,query,max_price,exclude_keywords,providers,daangn_region,created_at)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    watch.name,
                    watch.query,
                    watch.max_price,
                    json.dumps(watch.exclude_keywords, ensure_ascii=False),
                    json.dumps(watch.providers),
                    watch.daangn_region,
                    now,
                ),
            )
        self.conn.commit()

    def list_watches(self, *, enabled_only: bool = False) -> list[tuple[int, Watch, bool]]:
        sql = "SELECT * FROM managed_watches"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY id"
        rows = self.conn.execute(sql).fetchall()
        return [
            (
                int(row["id"]),
                Watch(
                    name=row["name"],
                    query=row["query"],
                    max_price=int(row["max_price"]),
                    exclude_keywords=json.loads(row["exclude_keywords"]),
                    providers=json.loads(row["providers"]),
                    daangn_region=row["daangn_region"],
                ),
                bool(row["enabled"]),
            )
            for row in rows
        ]

    def add_watch(self, name: str, max_price: int, region: str | None = None) -> int:
        if max_price <= 0:
            raise ValueError("max_price must be positive")
        now = datetime.now(UTC).isoformat()
        cur = self.conn.execute(
            """INSERT INTO managed_watches
            (name,query,max_price,exclude_keywords,providers,daangn_region,created_at)
            VALUES (?,?,?,'[]',?, ?,?)""",
            (name, name, max_price, json.dumps(["daangn", "joongna", "bunjang"]), region, now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def delete_watch(self, watch_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM managed_watches WHERE id=?", (watch_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def set_watch_enabled(self, watch_id: int, enabled: bool) -> bool:
        cur = self.conn.execute(
            "UPDATE managed_watches SET enabled=? WHERE id=?", (int(enabled), watch_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def set_max_price(self, watch_id: int, max_price: int) -> bool:
        if max_price <= 0:
            raise ValueError("max_price must be positive")
        cur = self.conn.execute(
            "UPDATE managed_watches SET max_price=? WHERE id=?", (max_price, watch_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def set_region(self, watch_id: int, region: str | None) -> bool:
        cur = self.conn.execute(
            "UPDATE managed_watches SET daangn_region=? WHERE id=?", (region, watch_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def update_exclude(self, watch_id: int, keyword: str, *, add: bool) -> bool:
        row = self.conn.execute(
            "SELECT exclude_keywords FROM managed_watches WHERE id=?", (watch_id,)
        ).fetchone()
        if row is None:
            return False
        words = json.loads(row["exclude_keywords"])
        if add and keyword not in words:
            words.append(keyword)
        if not add:
            words = [word for word in words if word != keyword]
        self.conn.execute(
            "UPDATE managed_watches SET exclude_keywords=? WHERE id=?",
            (json.dumps(words, ensure_ascii=False), watch_id),
        )
        self.conn.commit()
        return True

    def reserve_alert(self, watch_name: str, listing: Listing) -> bool:
        now = datetime.now(UTC).isoformat()
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO alert_receipts(watch_name,provider,external_id,alerted_at)
            VALUES (?,?,?,?)""",
            (watch_name, listing.provider, listing.external_id, now),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def observe(self, listing: Listing) -> Change:
        now = datetime.now(UTC).isoformat()
        row = self.conn.execute(
            "SELECT price FROM listings WHERE provider=? AND external_id=?",
            (listing.provider, listing.external_id),
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO listings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    listing.provider,
                    listing.external_id,
                    listing.title,
                    listing.url,
                    listing.price,
                    listing.location,
                    now,
                    now,
                ),
            )
            self.conn.execute(
                "INSERT INTO price_history(provider,external_id,price,observed_at) VALUES (?,?,?,?)",
                (listing.provider, listing.external_id, listing.price, now),
            )
            self.conn.commit()
            return Change("new", None, listing.price)

        old_price = row["price"]
        self.conn.execute(
            "UPDATE listings SET title=?,url=?,price=?,location=?,last_seen_at=? "
            "WHERE provider=? AND external_id=?",
            (
                listing.title,
                listing.url,
                listing.price,
                listing.location,
                now,
                listing.provider,
                listing.external_id,
            ),
        )
        kind = "same"
        if old_price != listing.price:
            self.conn.execute(
                "INSERT INTO price_history(provider,external_id,price,observed_at) VALUES (?,?,?,?)",
                (listing.provider, listing.external_id, listing.price, now),
            )
            if old_price is not None and listing.price is not None:
                kind = "price_down" if listing.price < old_price else "price_up"
            else:
                kind = "price_changed"
        self.conn.commit()
        return Change(kind, old_price, listing.price)

    def is_bootstrapped(self, watch_name: str, provider: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM scan_state WHERE watch_name=? AND provider=?", (watch_name, provider)
        ).fetchone() is not None

    def mark_bootstrapped(self, watch_name: str, provider: str) -> None:
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            "INSERT OR IGNORE INTO scan_state(watch_name,provider,bootstrapped_at) VALUES (?,?,?)",
            (watch_name, provider, now),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
