import asyncio
import json

from sale_bot.models import Watch, split_daangn_regions
from sale_bot.providers import (
    DaangnProvider,
    JoongnaProvider,
    _extract_daangn_articles,
    _extract_json_array,
    coerce_price,
    daangn_id_from_url,
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
    html = (
        '<script>self.__next_f.push([1,"x \\"items\\":'
        f'{payload} ,\\"changedProductFilterType\\":0"])</script>'
    )
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
    assert len(items) == 1
    assert items[0].external_id == "123"
    assert items[0].price == 950000
    assert items[0].title == "RX 9070 XT"


def test_coerce_numeric_price():
    assert coerce_price(950000) == 950000
    assert coerce_price("950,000원") == 950000
    assert coerce_price("950000") == 950000


def test_split_daangn_regions_deduplicates_and_limits():
    assert split_daangn_regions("복대동, 가경동, 복대동; 봉명동") == ["복대동", "가경동", "봉명동"]

    try:
        split_daangn_regions("1동,2동,3동,4동,5동,6동")
    except ValueError as exc:
        assert "region limit" in str(exc)
    else:
        raise AssertionError("more than five Daangn regions must be rejected")


def test_daangn_html_embedded_articles_parse_current_fields():
    rows = [
        {
            "id": "p7mskunj8ik8",
            "href": "/kr/buy-sell/rx-9070-xt-p7mskunj8ik8/",
            "title": "RX 9070 XT",
            "price": "850000",
            "thumbnail": "https://img.example/daangn.jpg",
            "locationName": "복대동",
            "status": "Ongoing",
        }
    ]
    html = f'<script>window.x={{"fleamarketArticles":{json.dumps(rows)}}}</script>'
    parsed = _extract_daangn_articles(html)
    provider = DaangnProvider()
    try:
        listings = provider._parse_articles(parsed)
    finally:
        asyncio.run(provider.close())

    assert len(listings) == 1
    assert listings[0].external_id == "p7mskunj8ik8"
    assert listings[0].price == 850000
    assert listings[0].location == "복대동"
    assert listings[0].image_url == "https://img.example/daangn.jpg"


def test_daangn_slug_id_uses_trailing_article_id():
    assert daangn_id_from_url("https://www.daangn.com/kr/buy-sell/rx-9070-xt-p7mskunj8ik8/") == "p7mskunj8ik8"
    assert daangn_id_from_url("https://www.daangn.com/kr/buy-sell/p7mskunj8ik8/") == "p7mskunj8ik8"


def test_daangn_multi_region_search_deduplicates_overlapping_listings(monkeypatch):
    provider = DaangnProvider()
    watch = Watch(
        name="gpu",
        query="9070 xt",
        max_price=900000,
        providers=["daangn"],
        daangn_region="복대동, 가경동",
    )
    calls: list[str | None] = []

    async def fake_fetch_articles(_watch: Watch, region_name: str | None) -> list[dict]:
        calls.append(region_name)
        common = {
            "href": "/kr/buy-sell/rx-9070-xt-123",
            "title": "RX 9070 XT",
            "price": 850000,
            "locationName": region_name,
            "status": "Ongoing",
        }
        if region_name == "복대동":
            return [common]
        return [
            common,
            {
                "href": "/kr/buy-sell/rx-9070-xt-456",
                "title": "RX 9070 XT 다른 매물",
                "price": 880000,
                "locationName": region_name,
                "status": "Ongoing",
            },
        ]

    monkeypatch.setattr(provider, "_fetch_articles", fake_fetch_articles)

    try:
        listings = asyncio.run(provider.search(watch))
    finally:
        asyncio.run(provider.close())

    assert calls == ["복대동", "가경동"]
    assert len(listings) == 2
    assert {listing.external_id for listing in listings} == {"123", "456"}
