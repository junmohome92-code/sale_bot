import argparse
import asyncio
import os

from .admin import run_discord_admin, run_telegram_admin
from .config import Settings, load_settings
from .models import Listing
from .notifiers import Notifier, format_message
from .providers import CHEONGJU_ALL, Provider, build_providers
from .storage import Store


def _db_path() -> str:
    return os.getenv("SALE_BOT_DB", "sale_bot.sqlite3")


def _reserve_for_delivery(
    store: Store,
    watch_name: str,
    listing: Listing,
    *,
    has_channels: bool,
    suppress_bootstrap: bool,
) -> bool:
    if suppress_bootstrap:
        store.reserve_alert(watch_name, listing)
        return False
    if not has_channels:
        return False
    return not store.has_alert_receipt(watch_name, listing)


async def _close_providers(providers: dict[str, Provider]) -> None:
    for provider in providers.values():
        try:
            await provider.close()
        except Exception as exc:  # noqa: BLE001 - cleanup must not stop daemon shutdown
            print(f"[{provider.name}] close failed: {exc}")


def _bootstrap_key(store: Store, watch, provider_name: str, settings: Settings) -> str:
    if provider_name != "daangn" or CHEONGJU_ALL not in watch.daangn_regions:
        return provider_name
    watch.daangn_batch_count = settings.daangn_full_region_batches
    watch.daangn_batch_index = store.next_daangn_batch(watch.name, watch.daangn_batch_count)
    return f"daangn:batch:{watch.daangn_batch_index}"


async def run_cycle(settings: Settings) -> None:
    store = Store(_db_path())
    store.seed_watches(settings.watches)
    notifier = Notifier(settings.request_timeout_seconds)
    providers = build_providers(settings.request_timeout_seconds)
    channels = notifier.configured_channels()
    if not channels:
        print("warning: no notification channel configured; results will only be stored")
    else:
        print(f"notification channels: {', '.join(channels)}")

    try:
        managed = store.list_watches(enabled_only=True)
        if not managed:
            print("no enabled watches configured")
        for _, watch, _ in managed:
            for provider_name in watch.providers:
                provider = providers[provider_name]
                bootstrap_key = _bootstrap_key(store, watch, provider_name, settings)
                bootstrapped = store.is_bootstrapped(watch.name, bootstrap_key)
                # Existing pre-batch installations used the plain daangn key.
                if provider_name == "daangn" and not bootstrapped:
                    bootstrapped = store.is_bootstrapped(watch.name, "daangn")
                try:
                    listings = await provider.search(watch)
                except Exception as exc:  # noqa: BLE001 - one provider must not stop other scans
                    print(f"[{provider_name}] search failed for {watch.name}: {exc}")
                    continue

                matched = 0
                alerts = 0
                for listing in listings:
                    if not watch.matches(listing):
                        continue
                    matched += 1
                    change = store.observe(listing)
                    suppress_bootstrap = settings.bootstrap_silently and not bootstrapped
                    should_deliver = _reserve_for_delivery(
                        store,
                        watch.name,
                        listing,
                        has_channels=bool(channels),
                        suppress_bootstrap=suppress_bootstrap,
                    )
                    if should_deliver:
                        delivered = await notifier.send(format_message(watch.name, listing, change))
                        if delivered and store.reserve_alert(watch.name, listing):
                            alerts += 1

                store.mark_bootstrapped(watch.name, bootstrap_key)
                mode = "baseline" if settings.bootstrap_silently and not bootstrapped else "active"
                batch = ""
                if provider_name == "daangn" and CHEONGJU_ALL in watch.daangn_regions:
                    batch = f" batch={watch.daangn_batch_index + 1}/{watch.daangn_batch_count}"
                print(
                    f"[{provider_name}] {watch.name}: fetched={len(listings)} "
                    f"matched={matched} alerts={alerts} mode={mode}{batch}"
                )
    finally:
        await _close_providers(providers)
        await notifier.close()
        store.close()


async def run_once() -> None:
    config_path = os.getenv("SALE_BOT_CONFIG", "config.yaml")
    settings = load_settings(config_path)
    await run_cycle(settings)


async def run_poller() -> None:
    config_path = os.getenv("SALE_BOT_CONFIG", "config.yaml")
    while True:
        interval = 300
        try:
            settings = load_settings(config_path)
            interval = settings.poll_interval_seconds
            await run_cycle(settings)
        except Exception as exc:  # noqa: BLE001 - polling daemon must recover next cycle
            print(f"poll cycle failed: {exc}")
        await asyncio.sleep(interval)


async def run_forever() -> None:
    await asyncio.gather(run_poller(), run_telegram_admin(), run_discord_admin())


def cli() -> None:
    parser = argparse.ArgumentParser(description="Korean second-hand market keyword tracker")
    parser.add_argument("--once", action="store_true", help="run one polling cycle and exit")
    args = parser.parse_args()
    asyncio.run(run_once() if args.once else run_forever())


if __name__ == "__main__":
    cli()
