import asyncio

import httpx

QUERY = "닌텐도 스위치2"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def _location(row: dict) -> object:
    for key in (
        "locationNames",
        "mainLocationName",
        "location",
        "location_name",
        "region",
        "regionName",
        "addressName",
    ):
        value = row.get(key)
        if value:
            return value
    return None


async def probe_joongna(client: httpx.AsyncClient) -> None:
    print("\n===== joongna api =====")
    url = "https://search-api.joongna.com/v3/search/all"
    for page in range(2):
        body = {
            "searchWord": QUERY,
            "keywordSource": "INPUT_KEYWORD",
            "actionDetailType": "NONE",
            "page": page,
            "size": 50,
            "sort": "RECENT_SORT",
            "filter": {},
        }
        response = await client.post(
            url,
            json=body,
            headers={
                **HEADERS,
                "Origin": "https://web.joongna.com",
                "Referer": "https://web.joongna.com/",
            },
        )
        print("PAGE", page, "STATUS", response.status_code)
        if response.status_code != 200:
            print("BODY", response.text[:500])
            continue
        payload = response.json()
        data = payload.get("data") or {}
        rows = (
            data.get("items")
            or data.get("productList")
            or data.get("products")
            or data.get("list")
            or (data.get("searchResult") or {}).get("items")
            or []
        )
        print("COUNT", len(rows))
        for row in rows[:8]:
            if not isinstance(row, dict):
                continue
            print(
                "ITEM",
                row.get("seq") or row.get("productSeq") or row.get("productId") or row.get("id"),
                row.get("title") or row.get("productTitle") or row.get("name"),
                row.get("price") or row.get("productPrice"),
                "LOC=",
                _location(row),
            )


async def probe_bunjang(client: httpx.AsyncClient) -> None:
    print("\n===== bunjang api =====")
    url = "https://api.bunjang.co.kr/api/1/find_v2.json"
    for page in range(2):
        response = await client.get(
            url,
            params={
                "q": QUERY,
                "order": "date",
                "page": page,
                "n": 100,
                "stat_device": "w",
                "req_ref": "search",
                "stat_category_required": "1",
                "version": "4",
            },
            headers={**HEADERS, "Referer": "https://m.bunjang.co.kr/"},
        )
        print("PAGE", page, "STATUS", response.status_code)
        if response.status_code != 200:
            print("BODY", response.text[:500])
            continue
        payload = response.json()
        rows = payload.get("list") or []
        print("COUNT", len(rows))
        for row in rows[:8]:
            if not isinstance(row, dict):
                continue
            print(
                "ITEM",
                row.get("pid"),
                row.get("name") or row.get("title"),
                row.get("price") or row.get("product_price"),
                "LOC=",
                _location(row),
            )


async def main() -> None:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        await probe_joongna(client)
        await probe_bunjang(client)


if __name__ == "__main__":
    asyncio.run(main())
