import argparse
import asyncio
import os

from .admin import run_discord_admin, run_telegram_admin
from .config import Settings, load_settings
from .notifiers import Notifier, format_message
from .providers import (
    Provider,
    build_providers,
    daangn_scope_key,
    has_daangn_all_scope,
)
from .storage import Change, Store


def _db_path() -> str:
    return os.getenv("SALE_BOT_DB", "sale_bot.sqlite3")


def _event_should_queue(change: Change, settings: Settings) -> bool:
    if change.kind == "new":
        return settings.alert_on_first_seen
    if change.kind == "price_down":
        return True
    if change.kind == "price_up":
        return settings.alert_on_price_increase
    return change.kind == "price_changed"


async def _close_providers(providers: dict[str, Provider]) -> None:
    for provider in providers.values():
        try:
            await provider.close()
        except Exception as exc:  # noqa: BLE001 - cleanup must not stop daemon shutdown
            print(f"[{provider.name}] close failed: {exc}")


def _bootstrap_key(store: Store, watch, provider_name: str, settings: Settings) -> str:
    if provider_name != "daangn" or not has_daangn_all_scope(watch.daangn_regions):
        return provider_name
    watch.daangn_batch_count = settings.daangn_region_batches
    watch.daangn_batch_index = store.next_daangn_batch(watch.name, watch.daangn_batch_count)
    scope_key = daangn_scope_key(watch.daangn_regions)
    return f"daangn:scope:{scope_key}:batch:{watch.daangn_batch_index}"


async def run_cycle(settings: Settings) -> None:
    store = Store(_db_path())
    store.seed_watches(settings.watches)
    notifier = Notifier(settings.request_timeout_seconds)
    providers = build_providers(settings.request_timeout_seconds)
    channels = notifier.configured_channels()
    if not channels:
        print(
            "warning: no notification channel configured; listings will be stored "
            "and eligible alerts kept pending"
        )
    else:
        print(f"notification channels: {', '.join(channels)}")

    try:
        managed = store.list_watches(enabled_only=True)
        if not managed:
            print("no enabled watches configured")
        for _, watch, _ in managed:
            for provider_name in watch.providers:
                provider = providers.get(provider_name)
                if provider is None:
                    print(f"[{provider_name}] unknown provider in stored watch {watch.name}")
                    continue

                bootstrap_key = _bootstrap_key(store, watch, provider_name, settings)
                bootstrapped = store.is_bootstrapped(watch.name, bootstrap_key)
                try:
                    listings = await provider.search(watch)
                except Exception as exc:  # noqa: BLE001 - one provider must not stop other scans
                    print(f"[{provider_name}] search failed for {watch.name}: {exc}")
                    continue

                matched = 0
                alerts = 0
                for listing in listings:
                    # Observe every fetched listing first so an out-of-range listing can later
                    # become a true price_down/price_up event when it enters the alert range.
                    change = store.observe(listing)

                    if not watch.matches(listing):
                        store.clear_pending_alert(watch.name, listing)
                        continue
                    matched += 1

                    if store.has_alert_receipt(watch.name, listing):
                        store.clear_pending_alert(watch.name, listing)
                        continue

                    suppress_bootstrap = settings.bootstrap_silently and not bootstrapped
                    if suppress_bootstrap:
                        store.reserve_alert(watch.name, listing)
                        continue

                    if _event_should_queue(change, settings):
                        store.queue_alert(watch.name, listing, change)

                    pending = store.pending_alert_change(watch.name, listing)
                    if pending is None or not channels:
                        continue

                    delivered = await notifier.send(format_message(watch.name, listing, pending))
                    if delivered and store.reserve_alert(watch.name, listing):
                        alerts += 1

                search_complete = getattr(provider, "last_search_complete", True)
                if search_complete:
                    store.mark_bootstrapped(watch.name, bootstrap_key)

                if settings.bootstrap_silently and not bootstrapped:
                    mode = "baseline" if search_complete else "baseline-partial"
                else:
                    mode = "active" if search_complete else "active-partial"

                batch = ""
                if provider_name == "daangn" and has_daangn_all_scope(watch.daangn_regions):
                    batch = f" batch={watch.daangn_batch_index + 1}/{watch.daangn_batch_count}"
                partial = ""
                errors = getattr(provider, "last_search_errors", [])
                if errors:
                    partial = f" region_errors={len(errors)}"
                print(
                    f"[{provider_name}] {watch.name}: fetched={len(listings)} "
                    f"matched={matched} alerts={alerts} mode={mode}{batch}{partial}"
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
