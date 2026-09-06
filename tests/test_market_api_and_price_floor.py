import asyncio
import sqlite3

from sale_bot.admin import _format_ignore_price, _watch_keyboard
from sale_bot.models import Listing, Watch
from sale_bot.region_policy import listing_matches_market_city
from sale_bot.runtime_providers import BunjangRuntimeProvider, JoongnaRuntimeProvider
from sale_bot.storage import Store


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeJoongnaClient:
    def __init__(self):
        self.calls = []

    async def post(self, _url, json):
        search_word = str(json["searchWord"])
        page = int(json["page"])
        self.calls.append((search_word, page))
        if page != 0:
            return FakeResponse({"data": {"items": []}})
        if search_word == "청주시 닌텐도 스위치2":
            return FakeResponse(
                {
                    "data": {
                        "items": [
                            {
                                "seq": 11,
                                "title": "닌텐도 스위치2 본체",
                                "price": 640000,
                                "state": 0,
                                "locationNames": ["충청북도 청주시 흥덕구 복대동"],
                                "url": "https://img.example/11.jpg",
                            },
                            {
                                "seq": 12,
                                "title": "닌텐도 스위치2 미개봉",
                                "price": 700000,
                                "state": 0,
                                "locationNames": ["대전광역시 유성구 봉명동"],
                            },
                        ]
                    }
                }
            )
        if search_word == "세종시 닌텐도 스위치2":
            return FakeResponse(
                {
                    "data": {
                        "items": [
                            {
                                "seq": 21,
                                "title": "닌텐도 스위치2 마리오카트 세트",
                                "price": 690000,
                                "state": 0,
                                "locationNames": ["세종특별자치시 세종특별자치시 보람동"],
                            },
                            {
                                "seq": 11,
                                "title": "닌텐도 스위치2 본체",
                                "price": 640000,
                                "state": 0,
                                "locationNames": ["충청북도 청주시 흥덕구 복대동"],
                            },
                        ]
                    }
                }
            )
        return FakeResponse({"data": {"items": []}})

    async def aclose(self):
        return None


class FakeBunjangClient:
    def __init__(self):
        self.pages = []

    async def get(self, _url, params):
        page = int(params["page"])
        self.pages.append(page)
        if page == 0:
            return FakeResponse(
                {
                    "list": [
                        {
                            "pid": 21,
                            "name": "닌텐도 스위치2",
                            "price": "660000",
                            "location": "세종특별자치시 나성동",
                            "product_image": "https://img.example/21.jpg",
                        },
                        {
                            "pid": 22,
                            "name": "닌텐도 스위치2",
                            "price": "680000",
                            "location": "서울특별시 강남구 역삼동",
                        },
                    ]
                }
            )
        return FakeResponse({"list": []})

    async def aclose(self):
        return None


def test_ignore_price_floor_is_inclusive_and_optional():
    watch = Watch(
        name="switch2",
        query="닌텐도 스위치2",
        max_price=1_000_000,
        ignore_price_at_or_below=10_000,
    )
    assert not watch.matches(Listing("daangn", "1", "x", 1, "https://x"))
    assert not watch.matches(Listing("daangn", "2", "x", 10_000, "https://x"))
    assert watch.matches(Listing("daangn", "3", "x", 10_001, "https://x"))
    assert _format_ignore_price(10_000) == "10,000원 이하 무시"
    assert _format_ignore_price(0) == "사용 안 함"


def test_store_migrates_existing_watch_table_and_persists_floor(tmp_path):
    db = tmp_path / "sale.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE managed_watches (
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
        CREATE TABLE runtime_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO runtime_state(key,value) VALUES ('schema_version','2');
        """
    )
    conn.commit()
    conn.close()

    store = Store(db)
    try:
        columns = {
            row["name"] for row in store.conn.execute("PRAGMA table_info(managed_watches)").fetchall()
        }
        assert "ignore_price_at_or_below" in columns
        watch_id = store.add_watch(
            "switch2",
            1_000_000,
            ["청주시"],
            ignore_price_at_or_below=10_000,
        )
        watch, _ = store.get_watch(watch_id)
        assert watch.ignore_price_at_or_below == 10_000
        assert store.set_ignore_price_at_or_below(watch_id, 20_000)
        watch, _ = store.get_watch(watch_id)
        assert watch.ignore_price_at_or_below == 20_000
    finally:
        store.close()


def test_watch_keyboard_exposes_ignore_price_button():
    labels = [
        button["text"]
        for row in _watch_keyboard(1, True)["inline_keyboard"]
        for button in row
    ]
    assert "🚫 무시가격" in labels


def test_joongna_api_searches_each_configured_city_and_deduplicates():
    provider = JoongnaRuntimeProvider()
    real_client = provider.client
    fake = FakeJoongnaClient()
    provider.client = fake
    watch = Watch(
        name="switch2",
        query="닌텐도 스위치2",
        max_price=1_000_000,
        daangn_regions=["청주시 전체", "세종시 전체"],
    )
    try:
        listings = asyncio.run(provider.search(watch))
    finally:
        asyncio.run(fake.aclose())
        asyncio.run(real_client.aclose())

    assert fake.calls == [
        ("청주시 닌텐도 스위치2", 0),
        ("세종시 닌텐도 스위치2", 0),
    ]
    assert {listing.external_id for listing in listings} == {"11", "12", "21"}
    by_id = {listing.external_id: listing for listing in listings}
    assert by_id["11"].location == "충청북도 청주시 흥덕구 복대동"
    assert by_id["21"].location == "세종특별자치시 세종특별자치시 보람동"
    assert listing_matches_market_city(watch, by_id["11"])
    assert listing_matches_market_city(watch, by_id["21"])
    assert not listing_matches_market_city(watch, by_id["12"])


def test_bunjang_api_uses_structured_location_for_city_filter():
    provider = BunjangRuntimeProvider()
    real_client = provider.client
    fake = FakeBunjangClient()
    provider.client = fake
    watch = Watch(
        name="switch2",
        query="닌텐도 스위치2",
        max_price=1_000_000,
        daangn_regions=["청주시 전체", "세종시 전체"],
    )
    try:
        listings = asyncio.run(provider.search(watch))
    finally:
        asyncio.run(fake.aclose())
        asyncio.run(real_client.aclose())
    assert fake.pages == [0, 1]
    assert listings[0].location == "세종특별자치시 나성동"
    assert listing_matches_market_city(watch, listings[0])
    assert not listing_matches_market_city(watch, listings[1])
