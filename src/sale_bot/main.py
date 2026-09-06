import argparse
import asyncio
import os
import time
from datetime import UTC, datetime

from .admin import run_telegram_admin
from .config import load_settings
from .models import Listing, Watch
from .notifiers import Notifier, format_message
from .providers import Provider
from .runtime_providers import DaangnRuntimeProvider, build_runtime_providers
from .storage import Change, Store, TrackingState


def _db_path() -> str:
    return os.getenv("SALE_BOT_DB", "sale_bot.sqlite3")


def _config_path() -> str:
    return os.getenv("SALE_BOT_CONFIG", "config.yaml")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _should_queue_alert(
    change: Change,
    state: TrackingState | None,
    listing: Listing,
    *,
    bootstrapped: bool,
) -> bool:
    if not bootstrapped or listing.price is None:
        return False
    if change.kind == "new":
        return True
    if change.kind not in {"price_down", "price_changed"}:
        return False
    if state is None or state.last_alert_price is None:
        return True
    return listing.price < state.last_alert_price


async def _process_listing(
    store: Store,
    notifier: Notifier,
    channels: list[str],
    watch_id: int,
    watch: Watch,
    listing: Listing,
    *,
    bootstrapped: bool,
) -> int:
    change = store.observe(watch_id, listing)
    state = store.tracking_state(watch_id, listing)

    if not watch.matches(listing):
        store.clear_pending_alert(watch_id, listing)
        return 0

    # A pending lower-price alert is stale if the price has risen before delivery.
    if change.kind == "price_up":
        store.clear_pending_alert(watch_id, listing)
        return 0

    if _should_queue_alert(change, state, listing, bootstrapped=bootstrapped):
        store.queue_alert(watch_id, listing, change)

    pending = store.pending_alert_change(watch_id, listing)
    if pending is None or not channels:
        return 0

    delivered = await notifier.send(format_message(watch.name, listing, pending, state))
    if delivered and store.mark_alert_delivered(watch_id, listing):
        return 1
    return 0


async def _run_daangn_round(
    provider: DaangnRuntimeProvider,
    notifier: Notifier,
) -> tuple[int, int, int]:
    store = Store(_db_path())
    channels = notifier.configured_channels()
    jobs = errors = alerts = 0
    try:
        for watch_id, watch, _ in store.list_watches(enabled_only=True):
            if "daangn" not in watch.providers:
                continue
            bootstrapped = store.is_bootstrapped(watch_id, "daangn")
            try:
                targets = await provider.all_region_targets(watch)
            except Exception as exc:  # noqa: BLE001 - one watch must not stop the provider loop
                errors += 1
                print(f"[daangn] region expansion failed for {watch.name}: {exc}")
                continue

            watch_errors = 0
            seen: set[str] = set()
            matched = 0
            fetched = 0
            watch_alerts = 0
            for region_name in targets:
                jobs += 1
                try:
                    listings = await provider.search_region(watch, region_name)
                except Exception as exc:  # noqa: BLE001 - continue remaining regions
                    errors += 1
                    watch_errors += 1
                    print(f"[daangn] {watch.name} / {region_name or '전체'} failed: {exc}")
                    continue
                for listing in listings:
                    if listing.external_id in seen:
                        continue
                    seen.add(listing.external_id)
                    fetched += 1
                    if watch.matches(listing):
                        matched += 1
                    sent = await _process_listing(
                        store,
                        notifier,
                        channels,
                        watch_id,
                        watch,
                        listing,
                        bootstrapped=bootstrapped,
                    )
                    alerts += sent
                    watch_alerts += sent

            if watch_errors == 0:
                store.mark_bootstrapped(watch_id, "daangn")
            mode = "active" if bootstrapped else "baseline"
            if watch_errors:
                mode += "-partial"
            print(
                f"[daangn] {watch.name}: targets={len(targets)} fetched={fetched} "
                f"matched={matched} alerts={watch_alerts} mode={mode} errors={watch_errors}"
            )
    finally:
        store.close()
    return jobs, errors, alerts


async def _run_simple_round(
    provider_name: str,
    provider: Provider,
    notifier: Notifier,
) -> tuple[int, int, int]:
    store = Store(_db_path())
    channels = notifier.configured_channels()
    jobs = errors = alerts = 0
    try:
        for watch_id, watch, _ in store.list_watches(enabled_only=True):
            if provider_name not in watch.providers:
                continue
            jobs += 1
            bootstrapped = store.is_bootstrapped(watch_id, provider_name)
            try:
                listings = await provider.search(watch)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                print(f"[{provider_name}] search failed for {watch.name}: {exc}")
                continue

            matched = 0
            watch_alerts = 0
            for listing in listings:
                if watch.matches(listing):
                    matched += 1
                sent = await _process_listing(
                    store,
                    notifier,
                    channels,
                    watch_id,
                    watch,
                    listing,
                    bootstrapped=bootstrapped,
                )
                alerts += sent
                watch_alerts += sent
            if getattr(provider, "last_search_complete", True):
                store.mark_bootstrapped(watch_id, provider_name)
            mode = "active" if bootstrapped else "baseline"
            print(
                f"[{provider_name}] {watch.name}: fetched={len(listings)} matched={matched} "
                f"alerts={watch_alerts} mode={mode}"
            )
    finally:
        store.close()
    return jobs, errors, alerts


async def run_provider_round(
    provider_name: str,
    provider: Provider,
    notifier: Notifier,
) -> float:
    started_iso = _now()
    started = time.monotonic()
    if provider_name == "daangn":
        if not isinstance(provider, DaangnRuntimeProvider):
            raise TypeError("daangn runtime provider required")
        jobs, errors, alerts = await _run_daangn_round(provider, notifier)
    else:
        jobs, errors, alerts = await _run_simple_round(provider_name, provider, notifier)
    duration = time.monotonic() - started
    status_store = Store(_db_path())
    try:
        status_store.record_provider_status(
            provider_name,
            started_at=started_iso,
            duration_seconds=duration,
            jobs=jobs,
            errors=errors,
            message=f"alerts={alerts}",
        )
    finally:
        status_store.close()
    return duration


async def _provider_loop(provider_name: str, provider: Provider, notifier: Notifier) -> None:
    while True:
        interval = 300
        started = time.monotonic()
        try:
            settings = load_settings(_config_path())
            interval = settings.poll_interval_seconds
            await run_provider_round(provider_name, provider, notifier)
        except Exception as exc:  # noqa: BLE001 - daemon must recover next round
            print(f"[{provider_name}] provider round failed: {exc}")
        elapsed = time.monotonic() - started
        # Five minutes is a target cycle. Heavy Daangn workloads run continuously rather
        # than pretending that a 20-keyword citywide scan still completes every five minutes.
        await asyncio.sleep(max(0.0, interval - elapsed))


async def _close_providers(providers: dict[str, Provider]) -> None:
    for provider in providers.values():
        try:
            await provider.close()
        except Exception as exc:  # noqa: BLE001
            print(f"[{provider.name}] close failed: {exc}")


async def run_once() -> None:
    settings = load_settings(_config_path())
    store = Store(_db_path())
    store.seed_watches(settings.watches)
    store.close()
    notifier = Notifier(settings.request_timeout_seconds)
    providers = build_runtime_providers(settings.request_timeout_seconds)
    channels = notifier.configured_channels()
    if not channels:
        print("warning: no notification channel configured; eligible alerts remain pending")
    try:
        await asyncio.gather(
            *(run_provider_round(name, provider, notifier) for name, provider in providers.items())
        )
    finally:
        await _close_providers(providers)
        await notifier.close()


async def run_forever() -> None:
    settings = load_settings(_config_path())
    store = Store(_db_path())
    store.seed_watches(settings.watches)
    store.close()
    notifier = Notifier(settings.request_timeout_seconds)
    providers = build_runtime_providers(settings.request_timeout_seconds)
    try:
        await asyncio.gather(
            *(_provider_loop(name, provider, notifier) for name, provider in providers.items()),
            run_telegram_admin(),
        )
    finally:
        await _close_providers(providers)
        await notifier.close()


def cli() -> None:
    parser = argparse.ArgumentParser(description="Korean second-hand market keyword tracker")
    parser.add_argument("--once", action="store_true", help="run one provider round and exit")
    args = parser.parse_args()
    asyncio.run(run_once() if args.once else run_forever())


if __name__ == "__main__":
    cli()
