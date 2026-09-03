from sale_bot.models import Listing, Watch
from sale_bot.notifiers import format_message
from sale_bot.providers import parse_price
from sale_bot.storage import Change


def test_parse_price():
    assert parse_price("850,000원") == 850000
    assert parse_price("가격 1,200,000 원") == 1200000
    assert parse_price("나눔") is None


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


def test_price_down_message():
    listing = Listing("joongna", "1", "GPU", 700000, "https://example.com/1")
    message = format_message("GPU watch", listing, Change("price_down", 800000, 700000))
    assert "가격 인하" in message.text
    assert "800,000원" in message.text
    assert "700,000원" in message.text
