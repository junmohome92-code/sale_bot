import argparse
import asyncio
import os

from .config import Settings, load_settings
from .notifiers import Notifier, format_message
from .providers import Provider, build_providers
from .storage import Store


async def _close_providers(providers: dict[str, Provider]) -> None:
    for provider in providers.values():
        try:
            await provider.close()
        except Exception as exc:
            print(f"[{provider.name}] close failed: {exc}")


async def run_cycle(settings: Settings) -> None:
    db_path = os.getenv("SALE_BOT_DB", "sale_bot.sqlite3")
    store = Store(db_path)
    notifier = Notifier(settings.request_timeout_seconds)
    providers = build_providers(settings.request_timeout_seconds)
    channels = notifier.configured_channels()
    if not channels:
        print("warning: no notification channel configured; results will only be stored")
    else:
        print(f"notification channels: {', '.join(channels)}")

    try:
        for watch in settings.watches:
            for provider_name in watch.providers:
                provider = providers[provider_name]
                bootstrapped = store.is_bootstrapped(watch.name, provider_name)
                try:
                    listings = await provider.search(watch)
                except Exception as exc:
                    print(f"[{provider_name}] search failed for {watch.name}: {exc}")
                    continue

                matched = 0
                alerts = 0
                for listing in listings:
                    if not watch.matches(listing):
                        continue
                    matched += 1
                    change = store.observe(listing)
                    suppress_bootstrap = (
                        settings.bootstrap_silently and not bootstrapped and change.kind == "new"
                    )
                    should_alert = not suppress_bootstrap and (
                        (change.kind == "new" and settings.alert_on_first_seen)
                        or change.kind == "price_down"
                        or change.kind == "price_changed"
                        or (change.kind == "price_up" and settings.alert_on_price_increase)
                    )
                    if should_alert:
                        alerts += 1
                        await notifier.send(format_message(watch.name, listing, change))

                store.mark_bootstrapped(watch.name, provider_name)
                mode = "baseline" if settings.bootstrap_silently and not bootstrapped else "active"
                print(
                    f"[{provider_name}] {watch.name}: fetched={len(listings)} "
                    f"matched={matched} alerts={alerts} mode={mode}"
                )
    finally:
        await _close_providers(providers)
        await notifier.close()
        store.close()


async def run_once() -> None:
    config_path = os.getenv("SALE_BOT_CONFIG", "config.yaml")
    settings = load_settings(config_path)
    await run_cycle(settings)


async def run_forever() -> None:
    config_path = os.getenv("SALE_BOT_CONFIG", "config.yaml")
    while True:
        interval = 300
        try:
            settings = load_settings(config_path)
            interval = settings.poll_interval_seconds
            await run_cycle(settings)
        except Exception as exc:
            print(f"poll cycle failed: {exc}")
        await asyncio.sleep(interval)


def cli() -> None:
    parser = argparse.ArgumentParser(description="Korean second-hand market keyword tracker")
    parser.add_argument("--once", action="store_true", help="run one polling cycle and exit")
    args = parser.parse_args()
    asyncio.run(run_once() if args.once else run_forever())


if __name__ == "__main__":
    cli()
