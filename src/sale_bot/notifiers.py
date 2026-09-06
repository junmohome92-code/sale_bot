import os
from dataclasses import dataclass

import httpx

from .models import Listing
from .storage import Change, TrackingState


@dataclass(slots=True)
class Message:
    text: str
    url: str


def _percent_drop(old: int | None, new: int | None) -> str | None:
    if old is None or new is None or old <= 0 or new >= old:
        return None
    return f"-{((old - new) / old) * 100:.1f}%"


def format_message(
    watch_name: str,
    listing: Listing,
    change: Change,
    state: TrackingState | None = None,
) -> Message:
    labels = {
        "new": "🆕 신규 조건충족",
        "price_down": "📉 가격 하락",
        "price_changed": "💱 가격 변경",
    }
    provider_labels = {
        "daangn": "당근",
        "joongna": "중고나라",
        "bunjang": "번개장터",
    }
    label = labels.get(change.kind, "🔔 매물 알림")
    price = f"{listing.price:,}원" if listing.price is not None else "가격 미상"
    lines = [f"{label} · {watch_name}", "", f"💰 {price}"]

    if (
        change.old_price is not None
        and listing.price is not None
        and change.old_price != listing.price
    ):
        drop = _percent_drop(change.old_price, listing.price)
        suffix = f" ({drop})" if drop else ""
        lines.append(f"📉 이전 가격: {change.old_price:,}원 → {listing.price:,}원{suffix}")

    if state and state.last_alert_price is not None and state.last_alert_price != listing.price:
        lines.append(f"🔔 마지막 알림가: {state.last_alert_price:,}원")

    if state and state.first_seen_price is not None and listing.price is not None:
        first_drop = _percent_drop(state.first_seen_price, listing.price)
        if first_drop:
            lines.append(
                f"📊 최초 발견: {state.first_seen_price:,}원 → "
                f"{listing.price:,}원 ({first_drop})"
            )

    if listing.location:
        lines.append(f"📍 {listing.location}")
    lines.append(f"🏪 {provider_labels.get(listing.provider, listing.provider)}")
    lines.extend(["", listing.title, "", f"🔗 {listing.url}"])
    return Message(text="\n".join(lines), url=listing.url)


class Notifier:
    def __init__(self, timeout: int = 20):
        self.client = httpx.AsyncClient(timeout=timeout)

    def configured_channels(self) -> list[str]:
        channels = []
        if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
            channels.append("telegram")
        if os.getenv("DISCORD_WEBHOOK_URL"):
            channels.append("discord")
        return channels

    async def send(self, message: Message) -> bool:
        jobs = []
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if token and chat_id:
            jobs.append(("telegram", self._telegram(token, chat_id, message.text)))
        webhook = os.getenv("DISCORD_WEBHOOK_URL")
        if webhook:
            jobs.append(("discord", self._discord(webhook, message.text)))

        delivered = False
        for channel, job in jobs:
            try:
                await job
                delivered = True
            except Exception as exc:  # noqa: BLE001 - one channel must not block another
                print(f"[{channel}] notifier error: {exc}")
        return delivered

    async def _telegram(self, token: str, chat_id: str, text: str) -> None:
        response = await self.client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": False},
        )
        response.raise_for_status()

    async def _discord(self, webhook: str, text: str) -> None:
        response = await self.client.post(webhook, json={"content": text[:1900]})
        response.raise_for_status()

    async def close(self) -> None:
        await self.client.aclose()
