import json

from sale_bot.providers import JoongnaProvider, _extract_json_array, coerce_price


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
