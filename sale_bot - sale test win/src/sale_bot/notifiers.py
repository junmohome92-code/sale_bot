import json
import os
from dataclasses import dataclass

import httpx

from .models import Listing
from .storage import Change


@dataclass(slots=True)
class Message:
    text: str
    url: str


def format_message(watch_name: str, listing: Listing, change: Change) -> Message:
    labels = {
        "new": "🆕 새 매물",
        "price_down": "📉 가격 인하",
        "price_up": "📈 가격 인상",
        "price_changed": "💱 가격 변경",
    }
    label = labels.get(change.kind, "🔔 변경")
    price = f"{listing.price:,}원" if listing.price is not None else "가격 미상"
    previous = ""
    if change.old_price is not None and change.old_price != listing.price:
        previous = f"\n이전 가격: {change.old_price:,}원"
    location = f"\n지역: {listing.location}" if listing.location else ""
    text = (
        f"{label} · {watch_name}\n"
        f"[{listing.provider}] {listing.title}\n"
        f"가격: {price}{previous}{location}\n"
        f"{listing.url}"
    )
    return Message(text=text, url=listing.url)


class Notifier:
    def __init__(self, timeout: int = 20):
        self.client = httpx.AsyncClient(timeout=timeout)

    def configured_channels(self) -> list[str]:
        channels = []
        if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
            channels.append("telegram")
        if os.getenv("DISCORD_WEBHOOK_URL"):
            channels.append("discord")
        if os.getenv("KAKAO_ACCESS_TOKEN"):
            channels.append("kakao")
        return channels

    async def send(self, message: Message) -> None:
        jobs = []
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if token and chat_id:
            jobs.append(("telegram", self._telegram(token, chat_id, message.text)))
        webhook = os.getenv("DISCORD_WEBHOOK_URL")
        if webhook:
            jobs.append(("discord", self._discord(webhook, message.text)))
        kakao_token = os.getenv("KAKAO_ACCESS_TOKEN")
        if kakao_token:
            jobs.append(("kakao", self._kakao(kakao_token, message.text, message.url)))
        for channel, job in jobs:
            try:
                await job
            except Exception as exc:  # noqa: BLE001 - one channel must not block the others
                print(f"[{channel}] notifier error: {exc}")

    async def _telegram(self, token: str, chat_id: str, text: str) -> None:
        response = await self.client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": False},
        )
        response.raise_for_status()

    async def _discord(self, webhook: str, text: str) -> None:
        response = await self.client.post(webhook, json={"content": text[:1900]})
        response.raise_for_status()

    async def _kakao(self, token: str, text: str, url: str) -> None:
        template = {
            "object_type": "text",
            "text": text[:1800],
            "link": {"web_url": url, "mobile_web_url": url},
        }
        response = await self.client.post(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            headers={"Authorization": f"Bearer {token}"},
            data={"template_object": json.dumps(template, ensure_ascii=False)},
        )
        response.raise_for_status()

    async def close(self) -> None:
        await self.client.aclose()
