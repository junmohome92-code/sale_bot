import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .models import Listing, Watch, split_daangn_regions

MAX_WATCH_SLOTS = 20
SCHEMA_VERSION = 2


@dataclass(slots=True)
class Change:
    kind: str
    old_price: int | None
    new_price: int | None


@dataclass(slots=True)
class TrackingState:
    first_seen_price: int | None
    current_price: int | None
    last_alert_price: int | None
    alert_count: int


def _now() -> str:
    return datetime.now(UTC).isoformat()


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
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _table_exists(self, name: str) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
            is not None
        )

    def _init_schema(self) -> None:
        # Preserve the watch table so current installations keep their configured slots.
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS managed_watches (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              query TEXT NOT NULL,
              min_price INTEGER,
              max_price INTEGER NOT NULL,
              exclude_keywords TEXT NOT NULL DEFAULT '[]',
              providers TEXT NOT NULL,
              daangn_region TEXT,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runtime_state (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            """
        )
        self._ensure_managed_watch_columns()

        current = self.conn.execute(
            "SELECT value FROM runtime_state WHERE key='schema_version'"
        ).fetchone()
        version = int(current["value"]) if current else 0
        if version < SCHEMA_VERSION:
            self._migrate_to_watch_scoped_tracking(version)

        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS watch_listing_state (
              watch_id INTEGER NOT NULL,
              provider TEXT NOT NULL,
              external_id TEXT NOT NULL,
              title TEXT NOT NULL,
              url TEXT NOT NULL,
              location TEXT,
              first_seen_price INTEGER,
              current_price INTEGER,
              last_alert_price INTEGER,
              first_seen_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              last_alert_at TEXT,
              alert_count INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (watch_id, provider, external_id),
              FOREIGN KEY (watch_id) REFERENCES managed_watches(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS watch_price_history (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              watch_id INTEGER NOT NULL,
              provider TEXT NOT NULL,
              external_id TEXT NOT NULL,
              price INTEGER,
              observed_at TEXT NOT NULL,
              FOREIGN KEY (watch_id) REFERENCES managed_watches(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_watch_price_history_lookup
              ON watch_price_history(watch_id,provider,external_id,observed_at);
            CREATE TABLE IF NOT EXISTS pending_alerts (
              watch_id INTEGER NOT NULL,
              provider TEXT NOT NULL,
              external_id TEXT NOT NULL,
              reason TEXT NOT NULL,
              old_price INTEGER,
              new_price INTEGER,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY (watch_id,provider,external_id),
              FOREIGN KEY (watch_id) REFERENCES managed_watches(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS watch_scan_state (
              watch_id INTEGER NOT NULL,
              provider TEXT NOT NULL,
              bootstrapped_at TEXT NOT NULL,
              PRIMARY KEY (watch_id,provider),
              FOREIGN KEY (watch_id) REFERENCES managed_watches(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS provider_status (
              provider TEXT PRIMARY KEY,
              last_round_started_at TEXT,
              last_round_finished_at TEXT,
              last_success_at TEXT,
              duration_seconds REAL,
              jobs INTEGER NOT NULL DEFAULT 0,
              errors INTEGER NOT NULL DEFAULT 0,
              message TEXT
            );
            """
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO runtime_state(key,value) VALUES ('schema_version',?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.commit()

    def _ensure_managed_watch_columns(self) -> None:
        columns = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(managed_watches)").fetchall()
        }
        if "min_price" not in columns:
            self.conn.execute("ALTER TABLE managed_watches ADD COLUMN min_price INTEGER")

    def _migrate_to_watch_scoped_tracking(self, previous_version: int) -> None:
        # Legacy state used only provider+listing id. It cannot be mapped safely to
        # overlapping watches, so v2 intentionally starts a fresh silent baseline.
        legacy_seeded = False
        if self._table_exists("app_state"):
            legacy_seeded = (
                self.conn.execute(
                    "SELECT 1 FROM app_state WHERE key='managed_watches_seeded'"
                ).fetchone()
                is not None
            )
        has_watches = int(
            self.conn.execute("SELECT COUNT(*) FROM managed_watches").fetchone()[0]
        ) > 0
        if previous_version == 0:
            for table in (
                "listings",
                "price_history",
                "alert_receipts",
                "alert_candidates",
                "scan_state",
            ):
                self.conn.execute(f"DROP TABLE IF EXISTS {table}")
            if self._table_exists("app_state"):
                self.conn.execute("DELETE FROM app_state WHERE key LIKE 'daangn_batch:%'")
        if has_watches or legacy_seeded:
            self.conn.execute(
                "INSERT OR REPLACE INTO runtime_state(key,value) "
                "VALUES ('watches_initialized','1')"
            )
        self.conn.commit()

    def seed_watches(self, watches: list[Watch]) -> None:
        initialized = self.conn.execute(
            "SELECT 1 FROM runtime_state WHERE key='watches_initialized'"
        ).fetchone()
        if initialized:
            return
        now = _now()
        for watch in watches[:MAX_WATCH_SLOTS]:
            if watch.max_price is None:
                continue
            self.conn.execute(
                """INSERT OR IGNORE INTO managed_watches
                (name,query,min_price,max_price,exclude_keywords,providers,daangn_region,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (
                    watch.name,
                    watch.query,
                    watch.min_price,
                    watch.max_price,
                    json.dumps(watch.exclude_keywords, ensure_ascii=False),
                    json.dumps(watch.providers),
                    _encode_regions(watch.daangn_regions),
                    now,
                ),
            )
        self.conn.execute(
            "INSERT OR REPLACE INTO runtime_state(key,value) "
            "VALUES ('watches_initialized','1')"
        )
        self.conn.commit()

    def _row_to_watch(self, row: sqlite3.Row) -> Watch:
        return Watch(
            name=str(row["name"]),
            query=str(row["query"]),
            min_price=int(row["min_price"]) if row["min_price"] is not None else None,
            max_price=int(row["max_price"]),
            exclude_keywords=json.loads(row["exclude_keywords"]),
            providers=json.loads(row["providers"]),
            daangn_regions=_decode_regions(row["daangn_region"]),
        )

    def list_watches(self, *, enabled_only: bool = False) -> list[tuple[int, Watch, bool]]:
        sql = "SELECT * FROM managed_watches"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY id"
        rows = self.conn.execute(sql).fetchall()
        return [
            (int(row["id"]), self._row_to_watch(row), bool(row["enabled"]))
            for row in rows
        ]

    def get_watch(self, watch_id: int) -> tuple[Watch, bool] | None:
        row = self.conn.execute(
            "SELECT * FROM managed_watches WHERE id=?", (watch_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_watch(row), bool(row["enabled"])

    def add_watch(
        self,
        name: str,
        max_price: int,
        region: str | list[str] | None = None,
        *,
        min_price: int | None = None,
        query: str | None = None,
        providers: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
    ) -> int:
        name = name.strip()
        query = (query or name).strip()
        if not name or not query:
            raise ValueError("watch name/query is required")
        if max_price <= 0:
            raise ValueError("max_price must be positive")
        if min_price is not None and min_price < 0:
            raise ValueError("min_price cannot be negative")
        if min_price is not None and min_price > max_price:
            raise ValueError("min_price cannot exceed max_price")
        count = int(self.conn.execute("SELECT COUNT(*) FROM managed_watches").fetchone()[0])
        if count >= MAX_WATCH_SLOTS:
            raise ValueError(f"watch slot limit reached ({MAX_WATCH_SLOTS})")
        if self.conn.execute("SELECT 1 FROM managed_watches WHERE name=?", (name,)).fetchone():
            raise ValueError("watch name already exists")

        cur = self.conn.execute(
            """INSERT INTO managed_watches
            (name,query,min_price,max_price,exclude_keywords,providers,daangn_region,created_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                name,
                query,
                min_price,
                max_price,
                json.dumps(exclude_keywords or [], ensure_ascii=False),
                json.dumps(providers or ["daangn", "joongna", "bunjang"]),
                _encode_regions(split_daangn_regions(region)),
                _now(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def delete_watch(self, watch_id: int) -> bool:
        if self.get_watch(watch_id) is None:
            return False
        with self.conn:
            self.conn.execute("DELETE FROM pending_alerts WHERE watch_id=?", (watch_id,))
            self.conn.execute("DELETE FROM watch_price_history WHERE watch_id=?", (watch_id,))
            self.conn.execute("DELETE FROM watch_listing_state WHERE watch_id=?", (watch_id,))
            self.conn.execute("DELETE FROM watch_scan_state WHERE watch_id=?", (watch_id,))
            self.conn.execute("DELETE FROM managed_watches WHERE id=?", (watch_id,))
        return True

    def set_watch_enabled(self, watch_id: int, enabled: bool) -> bool:
        cur = self.conn.execute(
            "UPDATE managed_watches SET enabled=? WHERE id=?", (int(enabled), watch_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def set_max_price(self, watch_id: int, max_price: int) -> bool:
        row = self.conn.execute(
            "SELECT min_price FROM managed_watches WHERE id=?", (watch_id,)
        ).fetchone()
        if row is None:
            return False
        if max_price <= 0:
            raise ValueError("max_price must be positive")
        if row["min_price"] is not None and int(row["min_price"]) > max_price:
            raise ValueError("max_price cannot be lower than min_price")
        self.conn.execute(
            "UPDATE managed_watches SET max_price=? WHERE id=?", (max_price, watch_id)
        )
        self.conn.commit()
        return True

    def set_price_range(self, watch_id: int, min_price: int | None, max_price: int) -> bool:
        if max_price <= 0:
            raise ValueError("max_price must be positive")
        if min_price is not None and min_price < 0:
            raise ValueError("min_price cannot be negative")
        if min_price is not None and min_price > max_price:
            raise ValueError("min_price cannot exceed max_price")
        cur = self.conn.execute(
            "UPDATE managed_watches SET min_price=?,max_price=? WHERE id=?",
            (min_price, max_price, watch_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def set_region(self, watch_id: int, region: str | list[str] | None) -> bool:
        if self.get_watch(watch_id) is None:
            return False
        with self.conn:
            self.conn.execute(
                "UPDATE managed_watches SET daangn_region=? WHERE id=?",
                (_encode_regions(split_daangn_regions(region)), watch_id),
            )
            # A region change is a new Daangn search universe for this slot.
            self.conn.execute(
                "DELETE FROM pending_alerts WHERE watch_id=? AND provider='daangn'",
                (watch_id,),
            )
            self.conn.execute(
                "DELETE FROM watch_price_history WHERE watch_id=? AND provider='daangn'",
                (watch_id,),
            )
            self.conn.execute(
                "DELETE FROM watch_listing_state WHERE watch_id=? AND provider='daangn'",
                (watch_id,),
            )
            self.conn.execute(
                "DELETE FROM watch_scan_state WHERE watch_id=? AND provider='daangn'",
                (watch_id,),
            )
        return True

    def update_exclude(self, watch_id: int, keyword: str, *, add: bool) -> bool:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("exclude keyword is required")
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

    def observe(self, watch_id: int, listing: Listing) -> Change:
        now = _now()
        row = self.conn.execute(
            """SELECT current_price FROM watch_listing_state
            WHERE watch_id=? AND provider=? AND external_id=?""",
            (watch_id, listing.provider, listing.external_id),
        ).fetchone()
        if row is None:
            self.conn.execute(
                """INSERT INTO watch_listing_state
                (watch_id,provider,external_id,title,url,location,first_seen_price,current_price,
                 first_seen_at,last_seen_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    watch_id,
                    listing.provider,
                    listing.external_id,
                    listing.title,
                    listing.url,
                    listing.location,
                    listing.price,
                    listing.price,
                    now,
                    now,
                ),
            )
            self.conn.execute(
                """INSERT INTO watch_price_history
                (watch_id,provider,external_id,price,observed_at) VALUES (?,?,?,?,?)""",
                (watch_id, listing.provider, listing.external_id, listing.price, now),
            )
            self.conn.commit()
            return Change("new", None, listing.price)

        old_price = row["current_price"]
        self.conn.execute(
            """UPDATE watch_listing_state
            SET title=?,url=?,location=?,current_price=?,last_seen_at=?
            WHERE watch_id=? AND provider=? AND external_id=?""",
            (
                listing.title,
                listing.url,
                listing.location,
                listing.price,
                now,
                watch_id,
                listing.provider,
                listing.external_id,
            ),
        )
        kind = "same"
        if old_price != listing.price:
            self.conn.execute(
                """INSERT INTO watch_price_history
                (watch_id,provider,external_id,price,observed_at) VALUES (?,?,?,?,?)""",
                (watch_id, listing.provider, listing.external_id, listing.price, now),
            )
            if old_price is not None and listing.price is not None:
                kind = "price_down" if listing.price < old_price else "price_up"
            else:
                kind = "price_changed"
        self.conn.commit()
        return Change(kind, old_price, listing.price)

    def tracking_state(self, watch_id: int, listing: Listing) -> TrackingState | None:
        row = self.conn.execute(
            """SELECT first_seen_price,current_price,last_alert_price,alert_count
            FROM watch_listing_state WHERE watch_id=? AND provider=? AND external_id=?""",
            (watch_id, listing.provider, listing.external_id),
        ).fetchone()
        if row is None:
            return None
        return TrackingState(
            row["first_seen_price"],
            row["current_price"],
            row["last_alert_price"],
            int(row["alert_count"]),
        )

    def queue_alert(self, watch_id: int, listing: Listing, change: Change) -> None:
        now = _now()
        self.conn.execute(
            """INSERT INTO pending_alerts
            (watch_id,provider,external_id,reason,old_price,new_price,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(watch_id,provider,external_id) DO UPDATE SET
              reason=excluded.reason,
              old_price=CASE
                WHEN pending_alerts.old_price IS NULL THEN excluded.old_price
                ELSE pending_alerts.old_price END,
              new_price=excluded.new_price,
              updated_at=excluded.updated_at""",
            (
                watch_id,
                listing.provider,
                listing.external_id,
                change.kind,
                change.old_price,
                listing.price,
                now,
                now,
            ),
        )
        self.conn.commit()

    def pending_alert_change(self, watch_id: int, listing: Listing) -> Change | None:
        row = self.conn.execute(
            """SELECT reason,old_price,new_price FROM pending_alerts
            WHERE watch_id=? AND provider=? AND external_id=?""",
            (watch_id, listing.provider, listing.external_id),
        ).fetchone()
        if row is None:
            return None
        return Change(str(row["reason"]), row["old_price"], row["new_price"])

    def clear_pending_alert(self, watch_id: int, listing: Listing) -> None:
        self.conn.execute(
            "DELETE FROM pending_alerts WHERE watch_id=? AND provider=? AND external_id=?",
            (watch_id, listing.provider, listing.external_id),
        )
        self.conn.commit()

    def mark_alert_delivered(self, watch_id: int, listing: Listing) -> bool:
        now = _now()
        with self.conn:
            cur = self.conn.execute(
                """UPDATE watch_listing_state
                SET last_alert_price=?,last_alert_at=?,alert_count=alert_count+1
                WHERE watch_id=? AND provider=? AND external_id=?""",
                (listing.price, now, watch_id, listing.provider, listing.external_id),
            )
            self.conn.execute(
                "DELETE FROM pending_alerts WHERE watch_id=? AND provider=? AND external_id=?",
                (watch_id, listing.provider, listing.external_id),
            )
        return cur.rowcount > 0

    def is_bootstrapped(self, watch_id: int, provider: str) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM watch_scan_state WHERE watch_id=? AND provider=?",
                (watch_id, provider),
            ).fetchone()
            is not None
        )

    def mark_bootstrapped(self, watch_id: int, provider: str) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO watch_scan_state(watch_id,provider,bootstrapped_at)
            VALUES (?,?,?)""",
            (watch_id, provider, _now()),
        )
        self.conn.commit()

    def record_provider_status(
        self,
        provider: str,
        *,
        started_at: str,
        duration_seconds: float,
        jobs: int,
        errors: int,
        message: str = "",
    ) -> None:
        finished = _now()
        success = finished if errors == 0 else None
        self.conn.execute(
            """INSERT INTO provider_status
            (provider,last_round_started_at,last_round_finished_at,last_success_at,
             duration_seconds,jobs,errors,message)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(provider) DO UPDATE SET
              last_round_started_at=excluded.last_round_started_at,
              last_round_finished_at=excluded.last_round_finished_at,
              last_success_at=COALESCE(excluded.last_success_at,provider_status.last_success_at),
              duration_seconds=excluded.duration_seconds,
              jobs=excluded.jobs,
              errors=excluded.errors,
              message=excluded.message""",
            (
                provider,
                started_at,
                finished,
                success,
                duration_seconds,
                jobs,
                errors,
                message[:500],
            ),
        )
        self.conn.commit()

    def provider_statuses(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM provider_status ORDER BY provider").fetchall()

    def close(self) -> None:
        self.conn.close()
