import asyncio

from sale_bot.models import Watch
from sale_bot.region_policy import listing_matches_market_city
from sale_bot.runtime_providers import BunjangRuntimeProvider, JoongnaRuntimeProvider


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
        print(f"[{name}] fetched={len(rows)} location_known={len(known)} city_match={len(city)} final={len(final)} complete={provider.last_search_complete}")
        if provider.last_search_errors:
            print(f"[{name}] errors={provider.last_search_errors}")
        for row in sorted(final, key=lambda item: item.price or 10**18)[:10]:
            print(f"[{name}] MATCH price={row.price} location={row.location} title={row.title} url={row.url}")
    finally:
        await provider.close()


async def main():
    await check("joongna", JoongnaRuntimeProvider(timeout=30))
    await check("bunjang", BunjangRuntimeProvider(timeout=30))


if __name__ == "__main__":
    asyncio.run(main())
