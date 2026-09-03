import argparse
import asyncio
import os

from .config import load_settings
from .notifiers import Notifier, format_message
from .providers import build_providers
from .storage import Store


async def run_once() -> None:
    config_path = os.getenv("SALE_BOT_CONFIG", "config.yaml")
    db_path = os.getenv("SALE_BOT_DB", "sale_bot.sqlite3")
    settings = load_settings(config_path)
    store = Store(db_path)
    notifier = Notifier(settings.request_timeout_seconds)
    providers = build_providers(settings.request_timeout_seconds)

    for watch in settings.watches:
        for provider_name in watch.providers:
            provider = providers[provider_name]
            try:
                listings = await provider.search(watch)
            except Exception as exc:
                print(f"[{provider_name}] search failed for {watch.name}: {exc}")
                continue
            for listing in listings:
                if not watch.matches(listing):
                    continue
                change = store.observe(listing)
                should_alert = (
                    (change.kind == "new" and settings.alert_on_first_seen)
                    or change.kind == "price_down"
                    or change.kind == "price_changed"
                    or (change.kind == "price_up" and settings.alert_on_price_increase)
                )
                if should_alert:
                    await notifier.send(format_message(watch.name, listing, change))


async def run_forever() -> None:
    config_path = os.getenv("SALE_BOT_CONFIG", "config.yaml")
    while True:
        settings = load_settings(config_path)
        await run_once()
        await asyncio.sleep(settings.poll_interval_seconds)


def cli() -> None:
    parser = argparse.ArgumentParser(description="Korean second-hand market keyword tracker")
    parser.add_argument("--once", action="store_true", help="run one polling cycle and exit")
    args = parser.parse_args()
    asyncio.run(run_once() if args.once else run_forever())


if __name__ == "__main__":
    cli()
