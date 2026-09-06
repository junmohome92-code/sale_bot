import asyncio

import pytest

from sale_bot.cache import BoundedTTLCache
from sale_bot.models import Listing, Watch
from sale_bot.region_policy import (
    city_labels_from_regions,
    listing_matches_market_city,
    market_city_text,
)
from sale_bot.runtime_control import (
    get_poll_interval,
    request_scan,
    set_poll_interval,
    wait_for_scan_or_timeout,
)
from sale_bot.runtime_providers import DaangnRuntimeProvider
from sale_bot.storage import Store


def test_bounded_cache_never_grows_past_limit():
    cache = BoundedTTLCache(maxsize=3, ttl_seconds=3600)
    for index in range(10):
        cache[index] = index
    assert len(cache) == 3
    assert 9 in cache
    assert 0 not in cache


def test_region_validator_treats_city_and_district_as_broad(monkeypatch):
    provider = DaangnRuntimeProvider(min_request_interval=0.5)

    async def fake_discover(scope):
        assert scope == "대전시 유성구"
        return [{"id": 1}, {"id": 2}]

    monkeypatch.setattr(provider, "_discover_scope_regions", fake_discover)
    try:
        result = asyncio.run(provider.validate_region_input("대전시 유성구"))
        assert result.canonical == "대전시 유성구 전체"
        assert result.target_count == 2
        assert result.broad
    finally:
        asyncio.run(provider.close())


def test_region_validator_returns_canonical_leaf(monkeypatch):
    provider = DaangnRuntimeProvider(min_request_interval=0.5)

    async def fake_resolve(_requested):
        return {
            "name": "봉명동",
            "name1": "대전광역시",
            "name2": "유성구",
            "name3": "봉명동",
        }

    monkeypatch.setattr(provider, "_resolve_region", fake_resolve)
    try:
        result = asyncio.run(provider.validate_region_input("대전시 유성구 봉명동"))
        assert result.canonical == "대전광역시 유성구 봉명동"
        assert not result.broad
    finally:
        asyncio.run(provider.close())


def test_region_validator_propagates_missing_region(monkeypatch):
    provider = DaangnRuntimeProvider(min_request_interval=0.5)

    async def fake_discover(_scope):
        raise RuntimeError("Daangn broad region not found")

    monkeypatch.setattr(provider, "_discover_scope_regions", fake_discover)
    try:
        with pytest.raises(RuntimeError, match="not found"):
            asyncio.run(provider.validate_region_input("청주시 강남구"))
    finally:
        asyncio.run(provider.close())


def test_non_daangn_markets_use_city_only():
    watch = Watch(
        name="gpu",
        query="9070xt",
        max_price=1200000,
        daangn_regions=["청주시 청원구 오창읍"],
    )
    assert city_labels_from_regions(watch.daangn_regions) == ["청주시"]
    assert market_city_text(watch) == "청주시"
    assert listing_matches_market_city(
        watch,
        Listing("joongna", "1", "9070xt", 900000, "https://x", "충북 청주시 흥덕구"),
    )
    assert not listing_matches_market_city(
        watch,
        Listing("joongna", "2", "9070xt", 900000, "https://x", "대전광역시 유성구"),
    )
    assert listing_matches_market_city(
        watch,
        Listing("bunjang", "3", "9070xt", 900000, "https://x", "청주 상당구"),
    )
    assert not listing_matches_market_city(
        watch,
        Listing("bunjang", "4", "9070xt", 900000, "https://x", None),
    )


def test_daangn_ignores_city_only_filter_because_provider_already_scopes_region():
    watch = Watch(
        name="gpu",
        query="9070xt",
        max_price=1200000,
        daangn_regions=["청주시 청원구 전체"],
    )
    listing = Listing("daangn", "1", "9070xt", 900000, "https://x", "오창읍")
    assert listing_matches_market_city(watch, listing)


def test_runtime_poll_interval_is_persisted(tmp_path):
    store = Store(tmp_path / "sale.sqlite3")
    try:
        assert get_poll_interval(store, 300) == 300
        set_poll_interval(store, 600)
        assert get_poll_interval(store, 300) == 600
        with pytest.raises(ValueError, match="unsupported"):
            set_poll_interval(store, 120)
    finally:
        store.close()


def test_scan_request_wakes_provider_waiter():
    request_scan("daangn")
    assert asyncio.run(wait_for_scan_or_timeout("daangn", 0))
