import asyncio

from sale_bot.models import Watch
from sale_bot.region_policy import listing_matches_market_city
from sale_bot.runtime_providers import BunjangRuntimeProvider, JoongnaRuntimeProvider


async def validate(name, provider, watch):
    try:
        rows = await provider.search(watch)
        city_rows = [row for row in rows if listing_matches_market_city(watch, row)]
        final_rows = [row for row in city_rows if watch.matches(row)]
        print(
            f"[{name}] fetched={len(rows)} city_match={len(city_rows)} "
            f"final={len(final_rows)} complete={provider.last_search_complete}"
        )
        for row in sorted(final_rows, key=lambda item: item.price or 10**18)[:10]:
            print(
                f"[{name}] MATCH price={row.price} location={row.location} "
                f"title={row.title} url={row.url}"
            )
    finally:
        await provider.close()


async def main():
    watch = Watch(
        name="닌텐도 스위치2",
        query="닌텐도 스위치2",
        max_price=1_000_000,
        ignore_price_at_or_below=10_000,
        daangn_regions=["청주시 전체", "세종시 전체"],
    )
    await validate("joongna", JoongnaRuntimeProvider(timeout=30), watch)
    await validate("bunjang", BunjangRuntimeProvider(timeout=30), watch)


if __name__ == "__main__":
    asyncio.run(main())
