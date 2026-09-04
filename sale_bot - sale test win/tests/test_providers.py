import asyncio
import json

import pytest

from sale_bot.models import Watch, split_daangn_regions
from sale_bot.providers import (
    CHEONGJU_ALL,
    CHEONGJU_NEIGHBORHOODS,
    DaangnProvider,
    JoongnaProvider,
    _extract_json_array,
    _select_region,
    coerce_price,
)


def test_extract_joongna_embedded_items():
    rows = [{"seq": 123, "price": 950000, "title": "RX 9070 XT", "url": "https://img.example/1.jpg", "sortDate": "2026-09-04T00:00:00", "mainLocationName": "청주시", "state": 0}]
    payload = json.dumps(rows)
    html = '<script>self.__next_f.push([1,"x \\"items\\":' f'{payload} ,\\"changedProductFilterType\\":0"])</script>'
    parsed = _extract_json_array(html, '"items":')
    assert parsed[0]["seq"] == 123


def test_joongna_embedded_parser_builds_listing():
    provider = JoongnaProvider()
    rows = [{"seq": 123, "price": 950000, "title": "RX 9070 XT", "url": "https://img.example/1.jpg", "sortDate": "2026-09-04T00:00:00", "mainLocationName": "청주시", "state": 0}]
    html = f'<script>window.x={{"items":{json.dumps(rows)},"changedProductFilterType":0}}</script>'
    items = provider._parse_embedded(html)
    assert len(items) == 1
    assert items[0].external_id == "123"
    assert items[0].price == 950000
    assert items[0].title == "RX 9070 XT"


def test_coerce_numeric_price():
    assert coerce_price(950000) == 950000
    assert coerce_price("950,000원") == 950000
    assert coerce_price("950000") == 950000


def test_split_daangn_regions_accepts_list_and_deduplicates():
    assert split_daangn_regions(["청주시 전체", "대전광역시 유성구 봉명동", "청주시 전체"]) == [
        "청주시 전체",
        "대전광역시 유성구 봉명동",
    ]


def test_region_selector_refuses_ambiguous_leaf_and_uses_context():
    locations = [
        {"name": "봉명동", "name1": "대전광역시", "name2": "유성구", "name3": "봉명동", "id": 1, "depth": 3},
        {"name": "봉명동", "name1": "충청북도", "name2": "청주시 흥덕구", "name3": "봉명동", "id": 2, "depth": 3},
    ]
    with pytest.raises(RuntimeError, match="ambiguous"):
        _select_region("봉명동", locations)
    selected = _select_region("충청북도 청주시 흥덕구 봉명동", locations)
    assert selected["id"] == 2


def test_citywide_targets_rotate_and_keep_explicit_region_every_cycle():
    provider = DaangnProvider()
    watch = Watch(
        name="gpu",
        query="9070 xt",
        max_price=900000,
        providers=["daangn"],
        daangn_regions=[CHEONGJU_ALL, "대전광역시 유성구 봉명동"],
        daangn_batch_count=5,
    )
    seen_city: set[str] = set()
    try:
        for batch_index in range(5):
            watch.daangn_batch_index = batch_index
            targets = provider.region_targets(watch)
            assert "대전광역시 유성구 봉명동" in targets
            seen_city.update(target for target in targets if target in CHEONGJU_NEIGHBORHOODS)
    finally:
        asyncio.run(provider.close())
    assert seen_city == set(CHEONGJU_NEIGHBORHOODS)
    assert len(CHEONGJU_NEIGHBORHOODS) == 43


def test_daangn_multi_region_search_deduplicates_overlapping_listings(monkeypatch):
    provider = DaangnProvider()
    watch = Watch(name="gpu", query="9070 xt", max_price=900000, providers=["daangn"], daangn_regions=["복대동", "가경동"])
    calls: list[str | None] = []

    async def fake_fetch_articles(_watch: Watch, region_name: str | None) -> list[dict]:
        calls.append(region_name)
        common = {"href": "/kr/buy-sell/rx-9070-xt-123", "title": "RX 9070 XT", "price": 850000, "region": {"name": region_name}}
        if region_name == "복대동":
            return [common]
        return [common, {"href": "/kr/buy-sell/rx-9070-xt-456", "title": "RX 9070 XT 다른 매물", "price": 880000, "region": {"name": region_name}}]

    monkeypatch.setattr(provider, "_fetch_articles", fake_fetch_articles)
    try:
        listings = asyncio.run(provider.search(watch))
    finally:
        asyncio.run(provider.close())

    assert calls == ["복대동", "가경동"]
    assert len(listings) == 2
    assert {listing.external_id for listing in listings} == {"rx-9070-xt-123", "rx-9070-xt-456"}
