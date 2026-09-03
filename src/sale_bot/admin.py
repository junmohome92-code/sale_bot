import asyncio
import os

import httpx
from discord import Intents
from discord.ext import commands

from .storage import MAX_WATCH_SLOTS, Store

HELP_TEXT = f"""감시 관리 명령어 (최대 {MAX_WATCH_SLOTS}개)
/add 상품명 | 최대가격 | 당근지역(선택)
/list
/price ID 최대가격
/region ID 지역명
/exclude ID add 단어
/exclude ID del 단어
/pause ID
/resume ID
/delete ID
/help

예: /add 9070 XT | 900000 | 청주시
"""


def _db_path() -> str:
    return os.getenv("SALE_BOT_DB", "sale_bot.sqlite3")


def handle_command(text: str) -> str:
    text = text.strip()
    if not text.startswith("/"):
        return HELP_TEXT
    command, _, args = text.partition(" ")
    command = command.lower()
    store = Store(_db_path())
    try:
        if command in {"/start", "/help"}:
            return HELP_TEXT
        if command == "/list":
            rows = store.list_watches()
            if not rows:
                return f"감시 항목이 없습니다. (0/{MAX_WATCH_SLOTS})"
            lines = [f"감시 슬롯: {len(rows)}/{MAX_WATCH_SLOTS}"]
            for watch_id, watch, enabled in rows:
                status = "ON" if enabled else "PAUSE"
                region = watch.daangn_region or "전체/미지정"
                excluded = ", ".join(watch.exclude_keywords) or "없음"
                lines.append(
                    f"#{watch_id} [{status}] {watch.name} / {watch.max_price:,}원 이하 / "
                    f"당근:{region} / 제외:{excluded}"
                )
            return "\n".join(lines)
        if command == "/add":
            parts = [part.strip() for part in args.split("|")]
            if len(parts) not in {2, 3} or not parts[0]:
                return "사용법: /add 상품명 | 최대가격 | 당근지역(선택)"
            max_price = int(parts[1].replace(",", ""))
            region = parts[2] if len(parts) == 3 and parts[2] else None
            watch_id = store.add_watch(parts[0], max_price, region)
            return f"추가 완료: #{watch_id} {parts[0]} / {max_price:,}원 이하"
        if command == "/price":
            watch_id_text, price_text = args.split(maxsplit=1)
            price = int(price_text.replace(",", ""))
            if not store.set_max_price(int(watch_id_text), price):
                return "해당 ID를 찾지 못했습니다."
            return f"가격 상한 변경 완료: #{watch_id_text} → {price:,}원"
        if command == "/region":
            watch_id_text, region = args.split(maxsplit=1)
            if not store.set_region(int(watch_id_text), region.strip()):
                return "해당 ID를 찾지 못했습니다."
            return f"당근 지역 변경 완료: #{watch_id_text} → {region.strip()}"
        if command == "/exclude":
            watch_id_text, action, keyword = args.split(maxsplit=2)
            if action not in {"add", "del"}:
                return "사용법: /exclude ID add|del 단어"
            if not store.update_exclude(int(watch_id_text), keyword.strip(), add=action == "add"):
                return "해당 ID를 찾지 못했습니다."
            action_text = "추가" if action == "add" else "삭제"
            return f"제외키워드 {action_text} 완료: #{watch_id_text} / {keyword.strip()}"
        if command in {"/pause", "/resume"}:
            watch_id = int(args.strip())
            enabled = command == "/resume"
            if not store.set_watch_enabled(watch_id, enabled):
                return "해당 ID를 찾지 못했습니다."
            return f"#{watch_id} {'재개' if enabled else '일시정지'} 완료"
        if command == "/delete":
            watch_id = int(args.strip())
            if not store.delete_watch(watch_id):
                return "해당 ID를 찾지 못했습니다."
            return f"#{watch_id} 삭제 완료"
        return HELP_TEXT
    except ValueError as exc:
        message = str(exc)
        if "slot limit" in message:
            return f"감시 슬롯이 가득 찼습니다. 최대 {MAX_WATCH_SLOTS}개까지 등록할 수 있습니다."
        if "already exists" in message:
            return "같은 이름의 감시 항목이 이미 있습니다."
        return "명령 형식이 올바르지 않습니다. /help 로 사용법을 확인하세요."
    except TypeError:
        return "명령 형식이 올바르지 않습니다. /help 로 사용법을 확인하세요."
    finally:
        store.close()


async def run_telegram_admin() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    allowed_chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not allowed_chat:
        return
    offset = 0
    async with httpx.AsyncClient(timeout=35) as client:
        while True:
            try:
                response = await client.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params={"timeout": 30, "offset": offset, "allowed_updates": '["message"]'},
                )
                response.raise_for_status()
                for update in response.json().get("result", []):
                    offset = max(offset, int(update["update_id"]) + 1)
                    message = update.get("message") or {}
                    chat_id = str((message.get("chat") or {}).get("id", ""))
                    text = message.get("text")
                    if chat_id != str(allowed_chat) or not isinstance(text, str):
                        continue
                    reply = handle_command(text)
                    sent = await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": allowed_chat, "text": reply},
                    )
                    sent.raise_for_status()
            except Exception as exc:  # noqa: BLE001 - admin loop must self-recover
                print(f"[telegram-admin] error: {exc}")
                await asyncio.sleep(5)


async def run_discord_admin() -> None:
    token = os.getenv("DISCORD_BOT_TOKEN")
    allowed_user = os.getenv("DISCORD_ADMIN_USER_ID")
    if not token or not allowed_user:
        return

    intents = Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="/", intents=intents, help_command=None)

    @bot.event
    async def on_ready():
        print(f"discord admin connected as {bot.user}")

    @bot.event
    async def on_message(message):
        if message.author.bot or str(message.author.id) != str(allowed_user):
            return
        if not message.content.startswith("/"):
            return
        await message.channel.send(handle_command(message.content)[:1900])

    try:
        await bot.start(token)
    except Exception as exc:  # noqa: BLE001 - daemon should keep polling if Discord admin fails
        print(f"[discord-admin] stopped: {exc}")
