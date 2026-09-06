import asyncio
import json
import re
from urllib.parse import quote, urljoin

import httpx

from sale_bot.models import Watch
from sale_bot.region_policy import listing_matches_market_city
from sale_bot.runtime_providers import BunjangRuntimeProvider, JoongnaRuntimeProvider

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


async def check(name, provider):
    watch = Watch(
        name="닌텐도 스위치2",
        query="닌텐도 스위치2",
        max_price=1_000_000,
        ignore_price_at_or_below=10_000,
        daangn_regions=["청주시 전체", "세종시 전체"],
    )
    try:
        rows = await provider.search(watch)
        known = [row for row in rows if row.location]
        city = [row for row in rows if listing_matches_market_city(watch, row)]
        final = [row for row in city if watch.matches(row)]
        print(
            f"[{name}] fetched={len(rows)} location_known={len(known)} "
            f"city_match={len(city)} final={len(final)} complete={provider.last_search_complete}"
        )
        for row in sorted(final, key=lambda item: item.price or 10**18)[:10]:
            print(
                f"[{name}] MATCH price={row.price} location={row.location} "
                f"title={row.title} url={row.url}"
            )
    finally:
        await provider.close()


async def inspect_joongna_contract():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=HEADERS) as client:
        body = {
            "searchWord": "닌텐도 스위치2",
            "keywordSource": "INPUT_KEYWORD",
            "actionDetailType": "NONE",
            "page": 0,
            "size": 50,
            "sort": "RECENT_SORT",
            "filter": {},
        }
        response = await client.post(
            "https://search-api.joongna.com/v3/search/all",
            json=body,
            headers={"Origin": "https://web.joongna.com", "Referer": "https://web.joongna.com/"},
        )
        print("JOONGNA API STATUS", response.status_code)
        payload = response.json()
        data = payload.get("data") or {}
        print("TOP_KEYS", list(payload.keys()))
        print("DATA_KEYS", list(data.keys()))
        filter_blob = json.dumps(data.get("filter"), ensure_ascii=False, indent=2)
        print("FILTER_JSON_BEGIN")
        print(filter_blob[:30000])
        print("FILTER_JSON_END")
        search_component = json.dumps(data.get("searchFilterComponent"), ensure_ascii=False, indent=2)
        print("SEARCH_FILTER_COMPONENT", search_component[:10000])

        page_url = f"https://web.joongna.com/search/{quote('닌텐도 스위치2')}"
        html_response = await client.get(page_url)
        print("JOONGNA WEB STATUS", html_response.status_code, "len", len(html_response.text))
        scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html_response.text)
        print("SCRIPT_COUNT", len(scripts))
        needles = (
            "search-api.joongna.com/v3/search/all",
            "locationNames",
            "locationFilter",
            "regionFilter",
            "filterLocation",
            "우리동네",
        )
        hits = 0
        for src in scripts:
            try:
                script = await client.get(urljoin(page_url, src))
            except Exception:
                continue
            text = script.text
            for needle in needles:
                start = 0
                while True:
                    idx = text.find(needle, start)
                    if idx < 0:
                        break
                    print(
                        "JS_HIT",
                        needle,
                        src,
                        text[max(0, idx - 500) : idx + 900].replace("\n", " "),
                    )
                    hits += 1
                    if hits >= 40:
                        return
                    start = idx + len(needle)
        print("JS_HITS_TOTAL", hits)


async def main():
    await inspect_joongna_contract()
    await check("joongna", JoongnaRuntimeProvider(timeout=30))
    await check("bunjang", BunjangRuntimeProvider(timeout=30))


if __name__ == "__main__":
    asyncio.run(main())
