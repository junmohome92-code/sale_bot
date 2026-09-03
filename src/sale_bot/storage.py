import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import Listing


@dataclass(slots=True)
class Change:
    kind: str
    old_price: int | None
    new_price: int | None


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA journal_mode=WAL")
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
            """
        )
        self.conn.commit()

    def observe(self, listing: Listing) -> Change:
        now = datetime.now(timezone.utc).isoformat()
        row = self.conn.execute(
            "SELECT price FROM listings WHERE provider=? AND external_id=?",
            (listing.provider, listing.external_id),
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO listings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (listing.provider, listing.external_id, listing.title, listing.url, listing.price,
                 listing.location, now, now),
            )
            self.conn.execute(
                "INSERT INTO price_history(provider,external_id,price,observed_at) VALUES (?,?,?,?)",
                (listing.provider, listing.external_id, listing.price, now),
            )
            self.conn.commit()
            return Change("new", None, listing.price)

        old_price = row[0]
        self.conn.execute(
            "UPDATE listings SET title=?,url=?,price=?,location=?,last_seen_at=? WHERE provider=? AND external_id=?",
            (listing.title, listing.url, listing.price, listing.location, now,
             listing.provider, listing.external_id),
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
