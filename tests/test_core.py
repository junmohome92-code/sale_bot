import pytest

from sale_bot.admin import handle_command
from sale_bot.models import Listing, Watch
from sale_bot.notifiers import format_message
from sale_bot.providers import parse_price
from sale_bot.storage import MAX_WATCH_SLOTS, Change, Store


def test_parse_price_ignores_model_numbers():
    assert parse_price("850,000원") == 850000
    assert parse_price("가격 1,200,000 원") == 1200000
    assert parse_price("RX 9070 XT 950,000원") == 950000
    assert parse_price("9070 XT") is None
    assert parse_price("나눔") is None


def test_watch_filters_price_excluded_words_and_unknown_price():
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
    assert not watch.matches(Listing("bunjang", "4", "9070 XT", None, "https://x"))


def test_price_down_message():
    listing = Listing("joongna", "1", "GPU", 700000, "https://example.com/1")
    message = format_message("GPU watch", listing, Change("price_down", 800000, 700000))
    assert "가격 인하" in message.text
    assert "800,000원" in message.text
    assert "700,000원" in message.text
    assert message.url == listing.url


def test_store_bootstrap_state(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        assert not store.is_bootstrapped("gpu", "joongna")
        store.mark_bootstrapped("gpu", "joongna")
        assert store.is_bootstrapped("gpu", "joongna")
    finally:
        store.close()


def test_managed_watches_are_limited_to_three_slots(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        for index in range(MAX_WATCH_SLOTS):
            store.add_watch(f"item-{index}", 100000 + index)
        with pytest.raises(ValueError, match="slot limit"):
            store.add_watch("fourth", 200000)

        first_id = store.list_watches()[0][0]
        assert store.delete_watch(first_id)
        replacement_id = store.add_watch("replacement", 300000)
        assert replacement_id > 0
        assert len(store.list_watches()) == MAX_WATCH_SLOTS
    finally:
        store.close()


def test_exclude_keywords_are_configurable(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        watch_id = store.add_watch("9070 XT", 900000, "청주시")
        assert store.update_exclude(watch_id, "삽니다", add=True)
        watch = store.list_watches()[0][1]
        assert not watch.matches(Listing("joongna", "1", "9070 XT 삽니다", 800000, "https://x"))
        assert watch.matches(Listing("joongna", "2", "9070 XT 판매", 800000, "https://x"))

        assert store.update_exclude(watch_id, "삽니다", add=False)
        watch = store.list_watches()[0][1]
        assert "삽니다" not in watch.exclude_keywords
    finally:
        store.close()


def test_alert_receipt_allows_each_listing_only_once(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    listing = Listing("daangn", "abc", "9070 XT", 850000, "https://example.com/abc")
    try:
        assert store.reserve_alert("9070 XT", listing)
        assert not store.reserve_alert("9070 XT", listing)
    finally:
        store.close()

    reopened = Store(tmp_path / "sale.sqlite3")
    try:
        assert not reopened.reserve_alert("9070 XT", listing)
    finally:
        reopened.close()


def test_delete_watch_clears_bootstrap_and_alert_receipts(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    listing = Listing("daangn", "abc", "9070 XT", 850000, "https://example.com/abc")
    try:
        watch_id = store.add_watch("9070 XT", 900000)
        store.mark_bootstrapped("9070 XT", "daangn")
        assert store.reserve_alert("9070 XT", listing)
        assert store.delete_watch(watch_id)

        new_id = store.add_watch("9070 XT", 900000)
        assert new_id != watch_id
        assert not store.is_bootstrapped("9070 XT", "daangn")
        assert store.reserve_alert("9070 XT", listing)
    finally:
        store.close()


def test_seed_only_happens_once_even_after_all_watches_deleted(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    seed = [Watch(name="gpu", query="gpu", max_price=500000)]
    try:
        store.seed_watches(seed)
        watch_id = store.list_watches()[0][0]
        assert store.delete_watch(watch_id)
        store.seed_watches(seed)
        assert store.list_watches() == []
    finally:
        store.close()


def test_chat_command_slot_limit_and_exclude(tmp_path, monkeypatch):
    db_path = tmp_path / "commands.sqlite3"
    monkeypatch.setenv("SALE_BOT_DB", str(db_path))

    assert "추가 완료" in handle_command("/add GPU1 | 100000")
    assert "추가 완료" in handle_command("/add GPU2 | 200000")
    assert "추가 완료" in handle_command("/add GPU3 | 300000")
    assert "슬롯이 가득" in handle_command("/add GPU4 | 400000")
    assert "제외키워드 추가 완료" in handle_command("/exclude 1 add 삽니다")
    listing = handle_command("/list")
    assert "3/3" in listing
    assert "삽니다" in listing
