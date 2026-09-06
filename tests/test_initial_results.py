import asyncio

from sale_bot import admin
from sale_bot.config import load_settings
from sale_bot.main import (
    INITIAL_RESULT_LIMIT_PER_PROVIDER,
    _pick_initial_results,
    _should_queue_alert,
)
from sale_bot.models import Listing, Watch
from sale_bot.notifiers import format_initial_results
from sale_bot.region_policy import (
    city_labels_from_regions,
    listing_matches_market_city,
    market_city_text,
)
from sale_bot.runtime_control import get_poll_interval
from sale_bot.storage import Store


def test_default_poll_interval_is_fifteen_minutes(tmp_path):
    settings = load_settings(tmp_path / "missing.yaml")
    assert settings.poll_interval_seconds == 900

    store = Store(tmp_path / "sale.sqlite3")
    try:
        assert get_poll_interval(store) == 900
    finally:
        store.close()


def test_multiple_regions_map_to_multiple_market_cities():
    watch = Watch(
        name="gpu",
        query="gpu",
        max_price=1000000,
        daangn_regions=["청주시 전체", "세종특별자치시 전체"],
    )
    assert city_labels_from_regions(watch.daangn_regions) == ["청주시", "세종특별자치시"]
    assert market_city_text(watch) == "청주시, 세종특별자치시"
    assert listing_matches_market_city(
        watch,
        Listing("joongna", "1", "gpu", 900000, "https://x/1", "충북 청주시 흥덕구"),
    )
    assert listing_matches_market_city(
        watch,
        Listing("bunjang", "2", "gpu", 900000, "https://x/2", "세종특별자치시"),
    )
    assert not listing_matches_market_city(
        watch,
        Listing("joongna", "3", "gpu", 900000, "https://x/3", "대전광역시 유성구"),
    )


def test_initial_results_are_compact_and_include_direct_links():
    listings = [
        Listing("daangn", "1", "첫 매물", 800000, "https://example.com/1", "복대동"),
        Listing("daangn", "2", "둘째 매물", 900000, "https://example.com/2", "오창읍"),
    ]
    message = format_initial_results("9070xt", "daangn", listings, total_matched=7)
    assert "초기 검색 결과" in message.text
    assert "조건충족 7개" in message.text
    assert "https://example.com/1" in message.text
    assert "https://example.com/2" in message.text


def test_initial_result_limit_is_three_and_cheapest_first():
    listings = [
        Listing("joongna", str(price), f"item-{price}", price, f"https://x/{price}")
        for price in (900000, 700000, 800000, 600000, 1000000)
    ]
    selected = _pick_initial_results(listings)
    assert INITIAL_RESULT_LIMIT_PER_PROVIDER == 3
    assert [item.price for item in selected] == [600000, 700000, 800000]


def test_any_real_price_drop_alerts_even_after_a_price_rise(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        watch_id = store.add_watch("gpu", 1000000)
        listing = Listing("daangn", "x", "gpu", 800000, "https://x")
        store.observe(watch_id, listing)
        store.mark_bootstrapped(watch_id, "daangn")

        listing.price = 900000
        up = store.observe(watch_id, listing)
        state = store.tracking_state(watch_id, listing)
        assert not _should_queue_alert(up, state, listing, bootstrapped=True)

        listing.price = 850000
        down = store.observe(watch_id, listing)
        state = store.tracking_state(watch_id, listing)
        assert _should_queue_alert(down, state, listing, bootstrapped=True)
    finally:
        store.close()


def test_telegram_ui_has_no_manual_scan_button():
    payloads = [
        admin._menu_keyboard(),
        admin._settings_keyboard(900),
        admin._watch_keyboard(1, True),
    ]
    callbacks = [
        button.get("callback_data", "")
        for payload in payloads
        for row in payload["inline_keyboard"]
        for button in row
    ]
    assert all("scan" not in callback for callback in callbacks)
    assert "청주시, 세종시" in admin.HELP_TEXT
    assert "기본 검색주기: 15분" in admin.HELP_TEXT


def test_help_alias_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("SALE_BOT_DB", str(tmp_path / "sale.sqlite3"))
    assert "sale_bot 도움말" in asyncio.run(admin.handle_command("/?"))
