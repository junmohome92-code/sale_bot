import sqlite3

import pytest

from sale_bot.admin import handle_command
from sale_bot.config import Settings
from sale_bot.main import _event_should_queue
from sale_bot.models import Listing, Watch
from sale_bot.notifiers import format_message
from sale_bot.providers import parse_price
from sale_bot.storage import MAX_WATCH_SLOTS, Change, Store


def _settings(**overrides):
    values = {
        "poll_interval_seconds": 300,
        "alert_on_first_seen": True,
        "alert_on_price_increase": False,
        "bootstrap_silently": True,
        "request_timeout_seconds": 20,
        "daangn_region_batches": 5,
        "watches": [],
    }
    values.update(overrides)
    return Settings(**values)


def test_parse_price_ignores_model_numbers():
    assert parse_price("850,000원") == 850000
    assert parse_price("가격 1,200,000 원") == 1200000
    assert parse_price("RX 9070 XT 950,000원") == 950000
    assert parse_price("9070 XT") is None
    assert parse_price("나눔") is None


def test_watch_filters_min_max_excluded_words_and_unknown_price():
    watch = Watch(
        name="gpu",
        query="9070 xt",
        min_price=500000,
        max_price=1000000,
        exclude_keywords=["삽니다"],
    )
    assert watch.matches(Listing("bunjang", "1", "9070 XT 팝니다", 800000, "https://x"))
    assert not watch.matches(Listing("bunjang", "2", "9070 XT 삽니다", 800000, "https://x"))
    assert not watch.matches(Listing("bunjang", "3", "9070 XT", 1200000, "https://x"))
    assert not watch.matches(Listing("bunjang", "4", "9070 XT", 40000, "https://x"))
    assert not watch.matches(Listing("bunjang", "5", "9070 XT", None, "https://x"))


def test_alert_policy_uses_config_flags():
    default = _settings()
    assert _event_should_queue(Change("new", None, 800000), default)
    assert _event_should_queue(Change("price_down", 900000, 800000), default)
    assert not _event_should_queue(Change("price_up", 700000, 800000), default)
    assert not _event_should_queue(Change("same", 800000, 800000), default)

    no_first = _settings(alert_on_first_seen=False)
    assert not _event_should_queue(Change("new", None, 800000), no_first)
    increases = _settings(alert_on_price_increase=True)
    assert _event_should_queue(Change("price_up", 700000, 800000), increases)


def test_price_down_message():
    listing = Listing("joongna", "1", "GPU", 700000, "https://example.com/1")
    message = format_message("GPU watch", listing, Change("price_down", 800000, 700000))
    assert "가격 인하" in message.text
    assert "800,000원" in message.text
    assert "700,000원" in message.text


def test_min_price_survives_database_round_trip(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        store.seed_watches(
            [Watch(name="gpu", query="gpu", min_price=500000, max_price=1000000)]
        )
        watch = store.list_watches()[0][1]
        assert watch.min_price == 500000
        assert watch.max_price == 1000000
        assert not watch.matches(Listing("joongna", "cheap", "gpu", 40000, "https://x"))
    finally:
        store.close()


def test_old_database_gets_min_price_column_and_seed_backfill(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE managed_watches (
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
        CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO managed_watches
          (name,query,max_price,exclude_keywords,providers,created_at)
        VALUES ('gpu','gpu',1000000,'[]','["joongna"]','now');
        INSERT INTO app_state(key,value) VALUES ('managed_watches_seeded','1');
        """
    )
    conn.commit()
    conn.close()

    store = Store(path)
    try:
        store.seed_watches(
            [Watch(name="gpu", query="gpu", min_price=500000, max_price=1000000)]
        )
        assert store.list_watches()[0][1].min_price == 500000
    finally:
        store.close()


def test_price_range_validation_and_admin_command(tmp_path, monkeypatch):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        watch_id = store.add_watch("gpu", 1000000, min_price=500000)
        assert store.set_price_range(watch_id, 600000, 900000)
        watch = store.list_watches()[0][1]
        assert (watch.min_price, watch.max_price) == (600000, 900000)
        with pytest.raises(ValueError, match="min_price"):
            store.set_price_range(watch_id, 950000, 900000)
    finally:
        store.close()

    db_path = tmp_path / "commands.sqlite3"
    monkeypatch.setenv("SALE_BOT_DB", str(db_path))
    assert "추가 완료" in handle_command("/add GPU | 500000~900000 | 대전시 전체")
    listing = handle_command("/list")
    assert "500,000~900,000원" in listing
    assert "대전시 전체" in listing
    assert "가격 범위 변경 완료" in handle_command("/range 1 600000 850000")


def test_observe_out_of_range_then_drop_is_real_price_down(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        expensive = Listing("joongna", "x", "gpu", 1200000, "https://x")
        cheap = Listing("joongna", "x", "gpu", 850000, "https://x")
        assert store.observe(expensive).kind == "new"
        change = store.observe(cheap)
        assert change.kind == "price_down"
        assert change.old_price == 1200000
        assert change.new_price == 850000
    finally:
        store.close()


def test_pending_alert_survives_until_receipt(tmp_path):
    path = tmp_path / "sale.sqlite3"
    listing = Listing("joongna", "abc", "GPU", 850000, "https://x")
    store = Store(path)
    try:
        store.queue_alert("gpu", listing, Change("new", None, 850000))
        pending = store.pending_alert_change("gpu", listing)
        assert pending is not None and pending.kind == "new"
    finally:
        store.close()

    reopened = Store(path)
    try:
        pending = reopened.pending_alert_change("gpu", listing)
        assert pending is not None
        assert reopened.reserve_alert("gpu", listing)
        assert reopened.pending_alert_change("gpu", listing) is None
        assert reopened.has_alert_receipt("gpu", listing)
    finally:
        reopened.close()


def test_region_change_resets_daangn_scan_and_batch_but_keeps_receipt(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    listing = Listing("daangn", "abc", "gpu", 850000, "https://x")
    try:
        watch_id = store.add_watch("gpu", 900000, "청주시 전체")
        store.mark_bootstrapped("gpu", "daangn:scope:old:batch:0")
        assert store.next_daangn_batch("gpu", 5) == 0
        assert store.reserve_alert("gpu", listing)
        assert store.set_region(watch_id, "대전시 전체")
        assert not store.is_bootstrapped("gpu", "daangn:scope:old:batch:0")
        assert store.next_daangn_batch("gpu", 5) == 0
        assert store.has_alert_receipt("gpu", listing)
    finally:
        store.close()


def test_managed_watches_are_limited_to_three_slots(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        for index in range(MAX_WATCH_SLOTS):
            store.add_watch(f"item-{index}", 100000 + index)
        with pytest.raises(ValueError, match="slot limit"):
            store.add_watch("fourth", 200000)
    finally:
        store.close()


def test_region_storage_supports_generic_citywide_and_legacy_text(tmp_path):
    path = tmp_path / "sale.sqlite3"
    store = Store(path)
    try:
        watch_id = store.add_watch("gpu", 900000, "대전시 전체, 경기도 성남시 전체")
        assert store.list_watches()[0][1].daangn_regions == [
            "대전시 전체",
            "경기도 성남시 전체",
        ]
        store.conn.execute(
            "UPDATE managed_watches SET daangn_region=? WHERE id=?", ("사창동, 우암동", watch_id)
        )
        store.conn.commit()
        assert store.list_watches()[0][1].daangn_regions == ["사창동", "우암동"]
    finally:
        store.close()


def test_daangn_rotation_cursor_persists(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        assert [store.next_daangn_batch("gpu", 5) for _ in range(7)] == [0, 1, 2, 3, 4, 0, 1]
    finally:
        store.close()
