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


def city_match(location_names, city):
    needle = city.replace(" ", "")
    aliases = {needle}
    if needle == "청주시":
        aliases.update({"충청북도청주시", "충북청주시"})
    if needle in {"세종시", "세종특별자치시"}:
        aliases.update({"세종시", "세종특별자치시"})
    for value in location_names or []:
        compact = str(value).replace(" ", "")
        if any(alias in compact for alias in aliases):
            return True
    return False


async def search(client, search_word, city):
    body = {
        "searchWord": search_word,
        "keywordSource": "INPUT_KEYWORD",
        "actionDetailType": "NONE",
        "page": 0,
        "size": 50,
        "sort": "RECENT_SORT",
        "filter": {},
    }
    response = await client.post(API, json=body)
    print("\nQUERY", search_word, "STATUS", response.status_code)
    payload = response.json()
    data = payload.get("data") or {}
    rows = data.get("items") or []
    print("TOTAL", data.get("totalSize"), "RETURNED", len(rows))

    known = 0
    matched = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        location_names = row.get("locationNames") or []
        main_location = row.get("mainLocationName")
        if location_names or main_location:
            known += 1
        if city_match(location_names, city) or city_match([main_location] if main_location else [], city):
            matched.append(row)

    print("LOCATION_KNOWN", known, "CITY_MATCH", len(matched))
    for row in matched[:10]:
        print(
            json.dumps(
                {
                    "id": row.get("seq") or row.get("id"),
                    "title": row.get("title"),
                    "price": row.get("price"),
                    "mainLocationName": row.get("mainLocationName"),
                    "locationNames": row.get("locationNames"),
                },
                ensure_ascii=False,
            )
        )


async def main():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=HEADERS) as client:
        for query, city in [
            ("닌텐도 스위치2", "청주시"),
            ("청주시 닌텐도 스위치2", "청주시"),
            ("청주 닌텐도 스위치2", "청주시"),
            ("세종시 닌텐도 스위치2", "세종시"),
            ("세종 닌텐도 스위치2", "세종시"),
        ]:
            await search(client, query, city)


if __name__ == "__main__":
    asyncio.run(main())
