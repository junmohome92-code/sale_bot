import asyncio
import json

import pytest

from sale_bot.models import Watch, split_daangn_regions
from sale_bot.providers import (
    DaangnProvider,
    JoongnaProvider,
    _extract_json_array,
    _select_region,
    coerce_price,
    daangn_all_scope,
    has_daangn_all_scope,
)


def test_extract_joongna_embedded_items():
    rows = [
        {
            "seq": 123,
            "price": 950000,
            "title": "RX 9070 XT",
            "url": "https://img.example/1.jpg",
            "sortDate": "2026-09-04T00:00:00",
            "mainLocationName": "청주시",
            "state": 0,
        }
    ]
    payload = json.dumps(rows)
    html = '<script>self.__next_f.push([1,"x \\"items\\":' f'{payload} ,\\"changedProductFilterType\\":0"])</script>'
    parsed = _extract_json_array(html, '"items":')
    assert parsed[0]["seq"] == 123


def test_joongna_embedded_parser_builds_listing():
    provider = JoongnaProvider()
    rows = [
        {
            "seq": 123,
            "price": 950000,
            "title": "RX 9070 XT",
            "url": "https://img.example/1.jpg",
            "sortDate": "2026-09-04T00:00:00",
            "mainLocationName": "청주시",
            "state": 0,
        }
    ]
    html = f'<script>window.x={{"items":{json.dumps(rows)},"changedProductFilterType":0}}</script>'
    items = provider._parse_embedded(html)
    try:
        assert len(items) == 1
        assert items[0].external_id == "123"
        assert items[0].price == 950000
    finally:
        asyncio.run(provider.close())


def test_coerce_numeric_price():
    assert coerce_price(950000) == 950000
    assert coerce_price("950,000원") == 950000
    assert coerce_price("950000") == 950000


def test_split_daangn_regions_accepts_list_and_deduplicates():
    assert split_daangn_regions(["청주시 전체", "대전시 전체", "청주시 전체"]) == [
        "청주시 전체",
        "대전시 전체",
    ]


def test_broad_region_parser_is_generic():
    assert daangn_all_scope("청주시 전체") == "청주시"
    assert daangn_all_scope("대전시 전체") == "대전시"
    assert daangn_all_scope("경기도 성남시 전체") == "경기도 성남시"
    assert daangn_all_scope("분당구") is None
    assert has_daangn_all_scope(["분당구", "성남시 전체"])


def test_region_selector_refuses_ambiguous_leaf_and_wrong_context():
    locations = [
        {
            "name": "봉명동",
            "name1": "대전광역시",
            "name2": "유성구",
            "name3": "봉명동",
            "id": 1,
            "depth": 3,
        },
        {
            "name": "봉명동",
            "name1": "충청북도",
            "name2": "청주시 흥덕구",
            "name3": "봉명동",
            "id": 2,
            "depth": 3,
        },
    ]
    with pytest.raises(RuntimeError, match="ambiguous"):
        _select_region("봉명동", locations)
    assert _select_region("충청북도 청주시 흥덕구 봉명동", locations)["id"] == 2
    with pytest.raises(RuntimeError, match="requested context"):
        _select_region("경기도 성남시 봉명동", [locations[0]])


def _region(name1, name2, name3, name2_id, name3_id):
    return {
        "name": name3,
        "name1": name1,
        "name2": name2,
        "name3": name3,
        "name1Id": 1,
        "name2Id": name2_id,
        "name3Id": name3_id,
        "id": name3_id,
        "depth": 3,
    }


def _fake_region_api():
    daejeon = [
        _region("대전광역시", "동구", "가양동", 101, 1001),
        _region("대전광역시", "중구", "은행동", 102, 1002),
        _region("대전광역시", "서구", "둔산동", 103, 1003),
        _region("대전광역시", "유성구", "봉명동", 104, 1004),
        _region("대전광역시", "대덕구", "법동", 105, 1005),
    ]
    seongnam = [
        _region("경기도", "성남시 수정구", "태평동", 201, 2001),
        _region("경기도", "성남시 중원구", "성남동", 202, 2002),
        _region("경기도", "성남시 분당구", "정자동", 203, 2003),
    ]
    return {
        "대전시": daejeon,
        "대전": daejeon,
        "동구": [daejeon[0], _region("대전광역시", "동구", "대동", 101, 1011)],
        "중구": [daejeon[1], _region("대전광역시", "중구", "오류동", 102, 1012)],
        "서구": [daejeon[2], _region("대전광역시", "서구", "월평동", 103, 1013)],
        "유성구": [daejeon[3], _region("대전광역시", "유성구", "상대동", 104, 1014)],
        "대덕구": [daejeon[4], _region("대전광역시", "대덕구", "송촌동", 105, 1015)],
        "경기도 성남시": seongnam,
        "성남시": seongnam,
        "성남": seongnam,
        "수정구": [seongnam[0], _region("경기도", "성남시 수정구", "신흥동", 201, 2011)],
        "중원구": [seongnam[1], _region("경기도", "성남시 중원구", "은행동", 202, 2012)],
        "분당구": [seongnam[2], _region("경기도", "성남시 분당구", "서현동", 203, 2013)],
    }


def test_generic_citywide_discovery_supports_daejeon_and_seongnam(monkeypatch):
    provider = DaangnProvider()
    api = _fake_region_api()

    async def fake_candidates(keyword):
        return api.get(keyword, [])

    monkeypatch.setattr(provider, "_region_candidates", fake_candidates)
    try:
        daejeon = Watch(
            name="switch",
            query="스위치2",
            max_price=900000,
            providers=["daangn"],
            daangn_regions=["대전시 전체"],
            daangn_batch_count=5,
        )
        seen = set()
        for batch_index in range(5):
            daejeon.daangn_batch_index = batch_index
            seen.update(asyncio.run(provider.region_targets(daejeon)))
        assert len(seen) == 10
        assert any("유성구 봉명동" in target for target in seen)

        seongnam = Watch(
            name="gpu",
            query="9070 xt",
            max_price=900000,
            providers=["daangn"],
            daangn_regions=["경기도 성남시 전체"],
            daangn_batch_count=3,
        )
        all_targets = asyncio.run(provider.all_region_targets(seongnam))
        assert len(all_targets) == 6
        assert any("성남시 분당구 서현동" in target for target in all_targets)
    finally:
        asyncio.run(provider.close())


def test_generic_citywide_discovery_rejects_ambiguous_bare_district(monkeypatch):
    provider = DaangnProvider()
    mixed = [
        _region("서울특별시", "중구", "필동", 301, 3001),
        _region("대전광역시", "중구", "은행동", 302, 3002),
    ]

    async def fake_candidates(keyword):
        return mixed if keyword in {"중구", "중"} else []

    monkeypatch.setattr(provider, "_region_candidates", fake_candidates)
    watch = Watch(name="x", query="x", max_price=100000, providers=["daangn"], daangn_regions=["중구 전체"])
    try:
        with pytest.raises(RuntimeError, match="broad region ambiguous"):
            asyncio.run(provider.all_region_targets(watch))
    finally:
        asyncio.run(provider.close())


def test_citywide_targets_keep_explicit_region_every_cycle(monkeypatch):
    provider = DaangnProvider()
    api = _fake_region_api()

    async def fake_candidates(keyword):
        return api.get(keyword, [])

    monkeypatch.setattr(provider, "_region_candidates", fake_candidates)
    watch = Watch(
        name="gpu",
        query="9070 xt",
        max_price=900000,
        providers=["daangn"],
        daangn_regions=["대전시 전체", "경기도 성남시 분당구 정자동"],
        daangn_batch_count=5,
    )
    try:
        for batch_index in range(5):
            watch.daangn_batch_index = batch_index
            targets = asyncio.run(provider.region_targets(watch))
            assert "경기도 성남시 분당구 정자동" in targets
    finally:
        asyncio.run(provider.close())


def test_daangn_partial_search_is_deduped_and_not_complete(monkeypatch):
    provider = DaangnProvider()
    watch = Watch(
        name="gpu",
        query="9070 xt",
        max_price=900000,
        providers=["daangn"],
        daangn_regions=["복대동", "가경동"],
    )

    async def fake_targets(_watch):
        return ["복대동", "가경동"]

    async def fake_fetch(_watch, region_name):
        if region_name == "가경동":
            raise RuntimeError("temporary region failure")
        return [{"href": "/kr/buy-sell/rx-123", "title": "RX 9070 XT", "price": 850000, "region": {"name": region_name}}]

    monkeypatch.setattr(provider, "region_targets", fake_targets)
    monkeypatch.setattr(provider, "_fetch_articles", fake_fetch)
    try:
        listings = asyncio.run(provider.search(watch))
        assert len(listings) == 1
        assert not provider.last_search_complete
        assert len(provider.last_search_errors) == 1
    finally:
        asyncio.run(provider.close())
