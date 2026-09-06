import asyncio
import sqlite3

import pytest

from sale_bot import admin
from sale_bot.config import Settings
from sale_bot.main import _should_queue_alert
from sale_bot.models import Listing, Watch
from sale_bot.notifiers import format_message
from sale_bot.providers import parse_price
from sale_bot.storage import MAX_WATCH_SLOTS, Store


def test_parse_price_ignores_model_numbers():
    assert parse_price("850,000원") == 850000
    assert parse_price("RX 9070 XT 950,000원") == 950000
    assert parse_price("9070 XT") is None


def test_watch_filters_price_and_excluded_words():
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


def test_transaction_type_filters_default_to_buying_only():
    watch = Watch(name="switch2", query="switch2", max_price=1_000_000)
    assert not watch.matches(
        Listing("joongna", "buy-1", "닌텐도 스위치2 삽니다", 600_000, "https://x")
    )
    assert not watch.matches(
        Listing("joongna", "buy-2", "닌텐도 스위치2 구합니다", 600_000, "https://x")
    )
    assert watch.matches(
        Listing("joongna", "sell-1", "닌텐도 스위치2 팝니다", 600_000, "https://x")
    )

    watch.exclude_buying_posts = False
    watch.exclude_selling_posts = True
    assert watch.matches(
        Listing("joongna", "buy-3", "닌텐도 스위치2 구매합니다", 600_000, "https://x")
    )
    assert not watch.matches(
        Listing("joongna", "sell-2", "닌텐도 스위치2 판매합니다", 600_000, "https://x")
    )


def test_twenty_watch_slots(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        for index in range(MAX_WATCH_SLOTS):
            store.add_watch(f"item-{index}", 100000 + index)
        assert len(store.list_watches()) == 20
        with pytest.raises(ValueError, match="slot limit"):
            store.add_watch("overflow", 200000)
    finally:
        store.close()


def test_overlapping_watches_keep_independent_price_state(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        first = store.add_watch("9070 XT", 1000000)
        second = store.add_watch("ASUS 9070 XT", 1000000)
        expensive = Listing("daangn", "same-item", "ASUS 9070 XT", 1200000, "https://x")
        cheaper = Listing("daangn", "same-item", "ASUS 9070 XT", 990000, "https://x")
        assert store.observe(first, expensive).kind == "new"
        assert store.observe(second, expensive).kind == "new"
        assert store.observe(first, cheaper).kind == "price_down"
        assert store.observe(second, cheaper).kind == "price_down"
    finally:
        store.close()


def test_every_lower_price_can_realert_but_same_or_up_cannot(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        watch_id = store.add_watch("9070 XT", 1000000)
        listing = Listing("daangn", "x", "9070 XT", 1200000, "https://x")
        store.observe(watch_id, listing)

        listing.price = 990000
        change = store.observe(watch_id, listing)
        state = store.tracking_state(watch_id, listing)
        assert _should_queue_alert(change, state, listing, bootstrapped=True)
        store.mark_alert_delivered(watch_id, listing)

        listing.price = 800000
        change = store.observe(watch_id, listing)
        state = store.tracking_state(watch_id, listing)
        assert _should_queue_alert(change, state, listing, bootstrapped=True)
        store.mark_alert_delivered(watch_id, listing)

        listing.price = 800000
        change = store.observe(watch_id, listing)
        state = store.tracking_state(watch_id, listing)
        assert not _should_queue_alert(change, state, listing, bootstrapped=True)

        listing.price = 900000
        change = store.observe(watch_id, listing)
        state = store.tracking_state(watch_id, listing)
        assert not _should_queue_alert(change, state, listing, bootstrapped=True)

        listing.price = 600000
        change = store.observe(watch_id, listing)
        state = store.tracking_state(watch_id, listing)
        assert _should_queue_alert(change, state, listing, bootstrapped=True)
    finally:
        store.close()


def test_bootstrap_never_alerts_existing_listing(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        watch_id = store.add_watch("gpu", 1000000)
        listing = Listing("joongna", "x", "gpu", 800000, "https://x")
        change = store.observe(watch_id, listing)
        state = store.tracking_state(watch_id, listing)
        assert not _should_queue_alert(change, state, listing, bootstrapped=False)
    finally:
        store.close()


def test_delete_watch_is_complete_slot_reset(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        watch_id = store.add_watch("gpu", 1000000)
        listing = Listing("daangn", "x", "gpu", 800000, "https://x")
        change = store.observe(watch_id, listing)
        store.queue_alert(watch_id, listing, change)
        store.mark_bootstrapped(watch_id, "daangn")
        assert store.delete_watch(watch_id)
        for table in (
            "managed_watches",
            "watch_listing_state",
            "watch_price_history",
            "pending_alerts",
            "watch_scan_state",
        ):
            assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        store.close()


def test_seed_is_one_time_even_after_all_slots_deleted(tmp_path):
    path = tmp_path / "sale.sqlite3"
    seed = [Watch(name="gpu", query="gpu", max_price=1000000)]
    store = Store(path)
    store.seed_watches(seed)
    watch_id = store.list_watches()[0][0]
    store.delete_watch(watch_id)
    store.close()

    reopened = Store(path)
    try:
        reopened.seed_watches(seed)
        assert reopened.list_watches() == []
    finally:
        reopened.close()


def test_legacy_database_migrates_to_clean_watch_scoped_baseline(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE managed_watches (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE, query TEXT NOT NULL, max_price INTEGER NOT NULL,
          exclude_keywords TEXT NOT NULL DEFAULT '[]', providers TEXT NOT NULL,
          daangn_region TEXT, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE TABLE listings (provider TEXT, external_id TEXT);
        CREATE TABLE price_history (id INTEGER);
        CREATE TABLE scan_state (watch_name TEXT, provider TEXT);
        CREATE TABLE alert_receipts (watch_name TEXT, provider TEXT, external_id TEXT);
        CREATE TABLE alert_candidates (watch_name TEXT, provider TEXT, external_id TEXT);
        CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO managed_watches(name,query,max_price,providers,created_at)
        VALUES ('gpu','gpu',1000000,'["daangn"]','now');
        INSERT INTO app_state VALUES ('managed_watches_seeded','1');
        """
    )
    conn.commit()
    conn.close()

    store = Store(path)
    try:
        assert len(store.list_watches()) == 1
        version = store.conn.execute(
            "SELECT value FROM runtime_state WHERE key='schema_version'"
        ).fetchone()[0]
        assert version == "4"
        for old_table in (
            "listings",
            "price_history",
            "scan_state",
            "alert_receipts",
            "alert_candidates",
        ):
            exists = store.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (old_table,)
            ).fetchone()
            assert exists is None
    finally:
        store.close()


def test_detailed_price_drop_message(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        watch_id = store.add_watch("GPU", 1000000)
        listing = Listing(
            "daangn",
            "1",
            "RX 9070 XT",
            1200000,
            "https://example.com/1",
            "복대동",
        )
        store.observe(watch_id, listing)
        listing.price = 800000
        change = store.observe(watch_id, listing)
        state = store.tracking_state(watch_id, listing)
        message = format_message("GPU", listing, change, state)
        assert "가격 하락" in message.text
        assert "1,200,000원" in message.text
        assert "800,000원" in message.text
        assert "당근" in message.text
        assert "복대동" in message.text
    finally:
        store.close()


def test_admin_list_and_help_alias(tmp_path, monkeypatch):
    db_path = tmp_path / "sale.sqlite3"
    monkeypatch.setenv("SALE_BOT_DB", str(db_path))
    store = Store(db_path)
    store.add_watch("gpu", 1000000)
    store.close()
    assert "20" in asyncio.run(admin.handle_command("/list"))
    assert "sale_bot 도움말" in asyncio.run(admin.handle_command("/도움말"))
    assert "sale_bot 도움말" in asyncio.run(admin.handle_command("/?"))


def test_settings_are_minimal_runtime_settings():
    settings = Settings(poll_interval_seconds=300, request_timeout_seconds=20, watches=[])
    assert settings.poll_interval_seconds == 300


def test_add_flow_asks_transaction_type_before_region(monkeypatch):
    sent = []

    async def fake_send(_client, _token, _chat_id, text, markup=None):
        sent.append((text, markup))

    monkeypatch.setattr(admin, "_send", fake_send)
    session = admin.AdminSession(step="add_ignore_price", data={})
    handled = asyncio.run(
        admin._handle_session_text(object(), "token", "1", "50000", session)
    )

    assert handled
    assert session.step == "add_transaction"
    assert session.data["exclude_buying_posts"] is True
    assert session.data["exclude_selling_posts"] is False
    assert "거래유형을 선택" in sent[-1][0]
    labels = [
        button["text"]
        for row in sent[-1][1]["inline_keyboard"]
        for button in row
    ]
    assert "✅ 삽니다 제외" in labels
    assert "⬜ 팝니다 허용" in labels
    assert "➡️ 다음" in labels


def test_add_transaction_keyboard_can_show_opposite_selection():
    keyboard = admin._add_transaction_keyboard(False, True)
    labels = [
        button["text"]
        for row in keyboard["inline_keyboard"]
        for button in row
    ]
    assert "⬜ 삽니다 허용" in labels
    assert "✅ 팝니다 제외" in labels
    assert admin._format_transaction_selection(False, True) == "삽니다 허용 · 팝니다 제외"
