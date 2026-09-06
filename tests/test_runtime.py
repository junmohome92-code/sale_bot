import asyncio

import pytest

from sale_bot.cache import BoundedTTLCache
from sale_bot.runtime_providers import DaangnRuntimeProvider


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
