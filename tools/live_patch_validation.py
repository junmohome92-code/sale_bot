import asyncio
import json

import httpx

API = "https://search-api.joongna.com/v3/search/all"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Origin": "https://web.joongna.com",
    "Referer": "https://web.joongna.com/",
}


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def locationish(row):
    return {
        key: value
        for key, value in row.items()
        if any(token in key.lower() for token in ("loc", "region", "area", "addr", "town", "dong"))
    }


def item_summary(payload):
    data = payload.get("data") or {}
    rows = data.get("items") or []
    result = []
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        result.append(
            {
                "id": row.get("seq") or row.get("id"),
                "title": row.get("title"),
                "locationish": locationish(row),
            }
        )
    return result


async def call(client, label, filter_value):
    body = {
        "searchWord": "닌텐도 스위치2",
        "keywordSource": "INPUT_KEYWORD",
        "actionDetailType": "NONE",
        "page": 0,
        "size": 20,
        "sort": "RECENT_SORT",
        "filter": filter_value,
    }
    response = await client.post(API, json=body)
    print("\nCASE", label)
    print("REQUEST_FILTER", compact(filter_value))
    print("STATUS", response.status_code)
    print("BODY_HEAD", response.text[:800].replace("\n", " "))
    if response.status_code != 200:
        return
    payload = response.json()
    data = payload.get("data") or {}
    print("TOTAL", data.get("totalSize"), "SIZE", data.get("size"))
    print("RETURNED_FILTER", compact(data.get("filter"))[:3000])
    print("ITEMS", compact(item_summary(payload))[:6000])


async def main():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=HEADERS) as client:
        await call(client, "baseline", {})
        candidates = [
            ("string-city", {"locationFilter": "청주시"}),
            ("list-city", {"locationFilter": ["청주시"]}),
            ("list-full-city", {"locationFilter": ["충청북도 청주시"]}),
            ("object-name", {"locationFilter": {"name": "청주시"}}),
            ("object-locationName", {"locationFilter": {"locationName": "청주시"}}),
            ("object-locationNames-list", {"locationFilter": {"locationNames": ["청주시"]}}),
            ("object-city", {"locationFilter": {"city": "청주시"}}),
            ("object-value", {"locationFilter": {"value": "청주시"}}),
            ("list-object-name", {"locationFilter": [{"name": "청주시"}]}),
            ("list-object-value", {"locationFilter": [{"value": "청주시"}]}),
            ("string-sejong", {"locationFilter": "세종시"}),
            ("list-sejong", {"locationFilter": ["세종시"]}),
        ]
        for label, value in candidates:
            try:
                await call(client, label, value)
            except Exception as exc:
                print("CASE_EXCEPTION", label, repr(exc))


if __name__ == "__main__":
    asyncio.run(main())
