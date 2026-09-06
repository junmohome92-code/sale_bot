import asyncio
import os
import time
from dataclasses import dataclass, field

import httpx

from .models import MAX_DAANGN_REGION_SPECS, split_daangn_regions
from .runtime_providers import DaangnRuntimeProvider
from .storage import MAX_WATCH_SLOTS, Store

HELP_TEXT = f"""🛒 sale_bot 도움말

• 감시 슬롯: 최대 {MAX_WATCH_SLOTS}개
• 기본 목표 검색주기: 5분
• 첫 실행 기존 매물: 알림 없음
• 목표가격 이하 새 매물: 알림
• 같은 매물도 가격이 하락하면 다시 알림
• 같은 가격 반복 / 가격 상승: 알림 없음

명령어
/menu  버튼 메뉴
/add  감시 추가
/list  감시 목록
/status  검색 상태
/price ID 최대가격
/range ID 최소가격 최대가격
/region ID 지역
/exclude ID add|del 단어
/pause ID
/resume ID
/delete ID
/help

지역 예:
청주시
청주시 청원구
청주시 청원구 오창읍
대전시 유성구
대전시 유성구 봉명동

시/군/구까지만 입력하면 해당 행정구역 전체로 검증합니다.
없는 지역이나 동명이의 지역은 등록 전에 오류로 알려드립니다.
"""

SESSION_TTL_SECONDS = 10 * 60
MAX_SESSIONS = 50


@dataclass(slots=True)
class AdminSession:
    step: str
    data: dict = field(default_factory=dict)
    updated_at: float = field(default_factory=time.monotonic)


_SESSIONS: dict[str, AdminSession] = {}


def _db_path() -> str:
    return os.getenv("SALE_BOT_DB", "sale_bot.sqlite3")


def _cleanup_sessions() -> None:
    now = time.monotonic()
    for key in list(_SESSIONS):
        if now - _SESSIONS[key].updated_at >= SESSION_TTL_SECONDS:
            _SESSIONS.pop(key, None)
    if len(_SESSIONS) > MAX_SESSIONS:
        stale = sorted(_SESSIONS.items(), key=lambda item: item[1].updated_at)[
            : len(_SESSIONS) - MAX_SESSIONS
        ]
        for key, _ in stale:
            _SESSIONS.pop(key, None)


def _set_session(chat_id: str, step: str, **data) -> None:
    _cleanup_sessions()
    _SESSIONS[chat_id] = AdminSession(step=step, data=data)


def _touch(session: AdminSession) -> None:
    session.updated_at = time.monotonic()


def _parse_price_spec(value: str) -> tuple[int | None, int]:
    value = value.replace(",", "").replace("원", "").strip()
    if "~" not in value:
        maximum = int(value)
        if maximum <= 0:
            raise ValueError("max_price must be positive")
        return None, maximum
    left, right = [part.strip() for part in value.split("~", 1)]
    if not left or not right:
        raise ValueError("invalid price range")
    minimum, maximum = int(left), int(right)
    if minimum < 0 or maximum <= 0 or minimum > maximum:
        raise ValueError("invalid price range")
    return minimum, maximum


def _format_price_range(min_price: int | None, max_price: int | None) -> str:
    if max_price is None:
        return "가격 제한 없음"
    if min_price is None:
        return f"{max_price:,}원 이하"
    return f"{min_price:,}~{max_price:,}원"


async def _validate_regions(value: str | list[str] | None) -> list[str]:
    regions = split_daangn_regions(value)
    if not regions:
        return []
    provider = DaangnRuntimeProvider()
    validated: list[str] = []
    try:
        for region in regions:
            result = await provider.validate_region_input(region)
            if result.canonical not in validated:
                validated.append(result.canonical)
    finally:
        await provider.close()
    return validated


def _status_text(store: Store) -> str:
    rows = store.list_watches()
    lines = ["🟢 sale_bot 상태", "", f"감시: {len(rows)} / {MAX_WATCH_SLOTS}"]
    statuses = store.provider_statuses()
    if not statuses:
        lines.append("\n아직 완료된 검색 라운드가 없습니다.")
        return "\n".join(lines)
    labels = {"daangn": "당근", "joongna": "중고나라", "bunjang": "번개장터"}
    lines.append("")
    for row in statuses:
        provider = str(row["provider"])
        errors = int(row["errors"])
        icon = "✅" if errors == 0 else "⚠️"
        duration = float(row["duration_seconds"] or 0)
        lines.append(
            f"{icon} {labels.get(provider, provider)}: {duration:.1f}초 / "
            f"작업 {int(row['jobs'])} / 오류 {errors}"
        )
    return "\n".join(lines)


def _list_text(store: Store) -> str:
    rows = store.list_watches()
    if not rows:
        return f"감시 항목이 없습니다. (0/{MAX_WATCH_SLOTS})"
    lines = [f"📋 감시 슬롯: {len(rows)}/{MAX_WATCH_SLOTS}"]
    for watch_id, watch, enabled in rows:
        status = "🟢" if enabled else "⏸"
        region = ", ".join(watch.daangn_regions) or "미지정"
        lines.append(
            f"#{watch_id} {status} {watch.name}\n"
            f"  💰 {_format_price_range(watch.min_price, watch.max_price)}\n"
            f"  📍 {region}"
        )
    return "\n".join(lines)


async def handle_command(text: str) -> str:
    text = text.strip()
    if text in {"도움말", "?", "/?", "/도움말"}:
        return HELP_TEXT
    if text in {"메뉴", "/메뉴"}:
        return "🛒 sale_bot 관리 메뉴"
    if not text.startswith("/"):
        return "명령을 찾지 못했습니다. /menu 또는 /help 를 입력해주세요."

    command, _, args = text.partition(" ")
    command = command.lower()
    store = Store(_db_path())
    try:
        if command in {"/start", "/help", "/menu"}:
            return HELP_TEXT if command == "/help" else "🛒 sale_bot 관리 메뉴"
        if command == "/list":
            return _list_text(store)
        if command == "/status":
            return _status_text(store)
        if command == "/add":
            if not args.strip():
                return (
                    "버튼 메뉴의 '➕ 감시 추가'를 누르거나 "
                    "/add 상품 | 최대가격 | 지역 형식으로 입력하세요."
                )
            parts = [part.strip() for part in args.split("|")]
            if len(parts) not in {2, 3} or not parts[0]:
                return "사용법: /add 상품명 | 최대가격 또는 최소~최대 | 당근지역(선택)"
            min_price, max_price = _parse_price_spec(parts[1])
            regions = await _validate_regions(parts[2]) if len(parts) == 3 and parts[2] else []
            watch_id = store.add_watch(parts[0], max_price, regions, min_price=min_price)
            region_text = ", ".join(regions) or "미지정"
            return (
                f"✅ 추가 완료: #{watch_id} {parts[0]}\n"
                f"💰 {_format_price_range(min_price, max_price)}\n📍 {region_text}"
            )
        if command == "/price":
            watch_id_text, price_text = args.split(maxsplit=1)
            price = int(price_text.replace(",", "").replace("원", ""))
            if not store.set_max_price(int(watch_id_text), price):
                return "해당 ID를 찾지 못했습니다."
            return f"✅ 가격 상한 변경: #{watch_id_text} → {price:,}원"
        if command == "/range":
            watch_id_text, min_text, max_text = args.split(maxsplit=2)
            minimum = int(min_text.replace(",", ""))
            maximum = int(max_text.replace(",", ""))
            if not store.set_price_range(int(watch_id_text), minimum, maximum):
                return "해당 ID를 찾지 못했습니다."
            return f"✅ 가격 범위 변경: #{watch_id_text} → {minimum:,}~{maximum:,}원"
        if command == "/region":
            watch_id_text, region_text = args.split(maxsplit=1)
            regions = await _validate_regions(region_text)
            if not store.set_region(int(watch_id_text), regions):
                return "해당 ID를 찾지 못했습니다."
            return f"✅ 당근 지역 변경: #{watch_id_text} → {', '.join(regions) or '미지정'}"
        if command == "/exclude":
            watch_id_text, action, keyword = args.split(maxsplit=2)
            if action not in {"add", "del"}:
                return "사용법: /exclude ID add|del 단어"
            if not store.update_exclude(int(watch_id_text), keyword.strip(), add=action == "add"):
                return "해당 ID를 찾지 못했습니다."
            return f"✅ 제외키워드 {'추가' if action == 'add' else '삭제'}: {keyword.strip()}"
        if command in {"/pause", "/resume"}:
            watch_id = int(args.strip())
            enabled = command == "/resume"
            if not store.set_watch_enabled(watch_id, enabled):
                return "해당 ID를 찾지 못했습니다."
            return f"✅ #{watch_id} {'재개' if enabled else '일시정지'}"
        if command == "/delete":
            watch_id = int(args.strip())
            if not store.delete_watch(watch_id):
                return "해당 ID를 찾지 못했습니다."
            return (
                f"🗑 #{watch_id} 완전 삭제 완료. "
                "해당 슬롯의 가격/알림/검색 이력도 초기화했습니다."
            )
        return HELP_TEXT
    except ValueError as exc:
        message = str(exc)
        if "slot limit" in message:
            return f"감시 슬롯이 가득 찼습니다. 최대 {MAX_WATCH_SLOTS}개입니다."
        if "region limit" in message:
            return f"당근 지역은 슬롯당 최대 {MAX_DAANGN_REGION_SPECS}개입니다."
        if "already exists" in message:
            return "같은 이름의 감시 항목이 이미 있습니다."
        return f"입력값을 확인해주세요: {message}"
    except RuntimeError as exc:
        message = str(exc)
        if "ambiguous" in message:
            return (
                "⚠️ 같은 이름의 지역이 여러 개 있습니다. "
                "시/구 등 상위 지역까지 함께 입력해주세요."
            )
        if "region" in message.lower():
            return (
                "❌ 당근에서 지역을 확인하지 못했습니다. 입력한 지역명을 확인해주세요.\n"
                f"{message}"
            )
        return f"처리 중 오류가 발생했습니다: {message}"
    except (TypeError, IndexError):
        return "명령 형식이 올바르지 않습니다. /help 로 사용법을 확인하세요."
    finally:
        store.close()


def _menu_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "➕ 감시 추가", "callback_data": "menu:add"},
                {"text": "📋 감시 목록", "callback_data": "menu:list"},
            ],
            [
                {"text": "📊 상태", "callback_data": "menu:status"},
                {"text": "🔔 알림 테스트", "callback_data": "menu:test"},
            ],
            [{"text": "❓ 도움말", "callback_data": "menu:help"}],
        ]
    }


def _watch_list_keyboard(store: Store) -> dict:
    rows = [
        [
            {
                "text": f"#{watch_id} {'🟢' if enabled else '⏸'} {watch.name}",
                "callback_data": f"watch:{watch_id}",
            }
        ]
        for watch_id, watch, enabled in store.list_watches()
    ]
    rows.append([{"text": "◀️ 메인", "callback_data": "menu:main"}])
    return {"inline_keyboard": rows}


def _watch_keyboard(watch_id: int, enabled: bool) -> dict:
    toggle = "pause" if enabled else "resume"
    toggle_text = "⏸ 일시정지" if enabled else "▶️ 재개"
    return {
        "inline_keyboard": [
            [
                {"text": "💰 가격 변경", "callback_data": f"watch:price:{watch_id}"},
                {"text": "📍 지역 변경", "callback_data": f"watch:region:{watch_id}"},
            ],
            [{"text": toggle_text, "callback_data": f"watch:{toggle}:{watch_id}"}],
            [{"text": "🗑 삭제", "callback_data": f"watch:deleteask:{watch_id}"}],
            [{"text": "◀️ 목록", "callback_data": "menu:list"}],
        ]
    }


async def _send(
    client: httpx.AsyncClient,
    token: str,
    chat_id: str,
    text: str,
    markup=None,
) -> None:
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": False}
    if markup is not None:
        payload["reply_markup"] = markup
    response = await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
    response.raise_for_status()


async def _answer_callback(client: httpx.AsyncClient, token: str, callback_id: str) -> None:
    response = await client.post(
        f"https://api.telegram.org/bot{token}/answerCallbackQuery",
        json={"callback_query_id": callback_id},
    )
    response.raise_for_status()


async def _handle_session_text(
    client: httpx.AsyncClient,
    token: str,
    chat_id: str,
    text: str,
    session: AdminSession,
) -> bool:
    _touch(session)
    if session.step == "add_name":
        session.data["name"] = text.strip()
        session.step = "add_price"
        await _send(
            client,
            token,
            chat_id,
            "💰 최대가격을 입력해주세요.\n예: 1000000\n범위: 500000~1000000",
        )
        return True
    if session.step == "add_price":
        try:
            minimum, maximum = _parse_price_spec(text)
        except (ValueError, TypeError):
            await _send(
                client,
                token,
                chat_id,
                "❌ 가격 형식을 확인해주세요. 예: 1000000 또는 500000~1000000",
            )
            return True
        session.data.update(min_price=minimum, max_price=maximum)
        session.step = "add_region"
        await _send(
            client,
            token,
            chat_id,
            "📍 당근 지역을 입력해주세요.\n"
            "예: 청주시 청원구 / 대전시 유성구 / 대전시 유성구 봉명동\n"
            "지역을 쓰지 않으려면 '건너뛰기'를 입력하세요.",
        )
        return True
    if session.step in {"add_region", "edit_region"}:
        try:
            regions = [] if text.strip() == "건너뛰기" else await _validate_regions(text)
        except (ValueError, RuntimeError) as exc:
            await _send(
                client,
                token,
                chat_id,
                f"❌ 지역 확인 실패\n{exc}\n\n상위 지역까지 포함해서 다시 입력해주세요.",
            )
            return True
        if session.step == "edit_region":
            store = Store(_db_path())
            try:
                store.set_region(int(session.data["watch_id"]), regions)
            finally:
                store.close()
            _SESSIONS.pop(chat_id, None)
            await _send(
                client,
                token,
                chat_id,
                f"✅ 지역 변경 완료: {', '.join(regions) or '미지정'}",
                _menu_keyboard(),
            )
            return True
        session.data["regions"] = regions
        session.step = "add_confirm"
        region_text = ", ".join(regions) or "미지정"
        summary = (
            f"✅ 등록할까요?\n\n상품: {session.data['name']}\n"
            f"💰 {_format_price_range(session.data['min_price'], session.data['max_price'])}\n"
            f"📍 {region_text}"
        )
        await _send(
            client,
            token,
            chat_id,
            summary,
            {
                "inline_keyboard": [
                    [
                        {"text": "✅ 등록", "callback_data": "session:add_confirm"},
                        {"text": "❌ 취소", "callback_data": "session:cancel"},
                    ]
                ]
            },
        )
        return True
    if session.step == "edit_price":
        try:
            minimum, maximum = _parse_price_spec(text)
        except (ValueError, TypeError):
            await _send(client, token, chat_id, "❌ 가격 형식을 확인해주세요.")
            return True
        store = Store(_db_path())
        try:
            store.set_price_range(int(session.data["watch_id"]), minimum, maximum)
        finally:
            store.close()
        _SESSIONS.pop(chat_id, None)
        await _send(client, token, chat_id, "✅ 가격 변경 완료", _menu_keyboard())
        return True
    return False


async def _handle_callback(
    client: httpx.AsyncClient,
    token: str,
    allowed_chat: str,
    callback: dict,
) -> None:
    callback_id = str(callback.get("id") or "")
    await _answer_callback(client, token, callback_id)
    data = str(callback.get("data") or "")
    message = callback.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id", ""))
    if chat_id != str(allowed_chat):
        return

    store = Store(_db_path())
    try:
        if data in {"menu:main", "menu:help"}:
            text = HELP_TEXT if data == "menu:help" else "🛒 sale_bot 관리 메뉴"
            await _send(client, token, chat_id, text, _menu_keyboard())
        elif data == "menu:add":
            if len(store.list_watches()) >= MAX_WATCH_SLOTS:
                await _send(
                    client,
                    token,
                    chat_id,
                    f"슬롯이 가득 찼습니다. ({MAX_WATCH_SLOTS}/{MAX_WATCH_SLOTS})",
                )
                return
            _set_session(chat_id, "add_name")
            await _send(
                client,
                token,
                chat_id,
                "➕ 감시할 상품/키워드를 입력해주세요.\n예: RX 9070 XT",
            )
        elif data == "menu:list":
            await _send(client, token, chat_id, _list_text(store), _watch_list_keyboard(store))
        elif data == "menu:status":
            await _send(client, token, chat_id, _status_text(store), _menu_keyboard())
        elif data == "menu:test":
            await _send(client, token, chat_id, "✅ sale_bot 알림 테스트 성공", _menu_keyboard())
        elif data.startswith("watch:"):
            parts = data.split(":")
            if len(parts) == 2:
                watch_id = int(parts[1])
                item = store.get_watch(watch_id)
                if item is None:
                    await _send(
                        client,
                        token,
                        chat_id,
                        "이미 삭제된 슬롯입니다.",
                        _menu_keyboard(),
                    )
                    return
                watch, enabled = item
                region = ", ".join(watch.daangn_regions) or "미지정"
                excluded = ", ".join(watch.exclude_keywords) or "없음"
                detail = (
                    f"#{watch_id} {'🟢 감시중' if enabled else '⏸ 일시정지'} · {watch.name}\n\n"
                    f"💰 {_format_price_range(watch.min_price, watch.max_price)}\n"
                    f"📍 {region}\n🚫 제외: {excluded}\n🏪 {', '.join(watch.providers)}"
                )
                await _send(
                    client,
                    token,
                    chat_id,
                    detail,
                    _watch_keyboard(watch_id, enabled),
                )
                return
            action, watch_id_text = parts[1], parts[2]
            watch_id = int(watch_id_text)
            if action == "price":
                _set_session(chat_id, "edit_price", watch_id=watch_id)
                await _send(
                    client,
                    token,
                    chat_id,
                    "💰 새 가격을 입력해주세요. 예: 1000000 또는 500000~1000000",
                )
            elif action == "region":
                _set_session(chat_id, "edit_region", watch_id=watch_id)
                await _send(
                    client,
                    token,
                    chat_id,
                    "📍 새 지역을 입력해주세요. 없는 지역은 적용되지 않습니다.",
                )
            elif action in {"pause", "resume"}:
                store.set_watch_enabled(watch_id, action == "resume")
                action_text = "재개" if action == "resume" else "일시정지"
                await _send(
                    client,
                    token,
                    chat_id,
                    f"✅ #{watch_id} {action_text}",
                    _menu_keyboard(),
                )
            elif action == "deleteask":
                item = store.get_watch(watch_id)
                if item is None:
                    await _send(client, token, chat_id, "이미 삭제된 슬롯입니다.")
                    return
                await _send(
                    client,
                    token,
                    chat_id,
                    f"⚠️ #{watch_id} {item[0].name} 슬롯을 완전 삭제할까요?\n"
                    "가격/알림/검색 이력도 함께 초기화됩니다.",
                    {
                        "inline_keyboard": [
                            [
                                {
                                    "text": "🔴 완전 삭제",
                                    "callback_data": f"watch:delete:{watch_id}",
                                },
                                {"text": "취소", "callback_data": "menu:list"},
                            ]
                        ]
                    },
                )
            elif action == "delete":
                store.delete_watch(watch_id)
                await _send(
                    client,
                    token,
                    chat_id,
                    f"🗑 #{watch_id} 완전 삭제 완료",
                    _menu_keyboard(),
                )
        elif data == "session:add_confirm":
            session = _SESSIONS.get(chat_id)
            if session is None or session.step != "add_confirm":
                await _send(
                    client,
                    token,
                    chat_id,
                    "입력 세션이 만료되었습니다. 다시 추가해주세요.",
                    _menu_keyboard(),
                )
                return
            watch_id = store.add_watch(
                session.data["name"],
                int(session.data["max_price"]),
                session.data.get("regions") or [],
                min_price=session.data.get("min_price"),
            )
            name = session.data["name"]
            _SESSIONS.pop(chat_id, None)
            await _send(
                client,
                token,
                chat_id,
                f"✅ #{watch_id} {name} 등록 완료",
                _menu_keyboard(),
            )
        elif data == "session:cancel":
            _SESSIONS.pop(chat_id, None)
            await _send(client, token, chat_id, "취소했습니다.", _menu_keyboard())
    finally:
        store.close()


async def run_telegram_admin() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    allowed_chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not allowed_chat:
        return
    offset = 0
    async with httpx.AsyncClient(timeout=35) as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{token}/setMyCommands",
                json={
                    "commands": [
                        {"command": "menu", "description": "버튼 관리 메뉴"},
                        {"command": "add", "description": "감시 추가"},
                        {"command": "list", "description": "감시 목록"},
                        {"command": "status", "description": "검색 상태"},
                        {"command": "help", "description": "도움말"},
                    ]
                },
            )
        except Exception as exc:  # noqa: BLE001 - command registration is optional
            print(f"[telegram-admin] setMyCommands failed: {exc}")

        while True:
            _cleanup_sessions()
            try:
                response = await client.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params={
                        "timeout": 30,
                        "offset": offset,
                        "allowed_updates": '["message","callback_query"]',
                    },
                )
                response.raise_for_status()
                for update in response.json().get("result", []):
                    offset = max(offset, int(update["update_id"]) + 1)
                    callback = update.get("callback_query")
                    if isinstance(callback, dict):
                        await _handle_callback(client, token, str(allowed_chat), callback)
                        continue

                    message = update.get("message") or {}
                    chat_id = str((message.get("chat") or {}).get("id", ""))
                    text = message.get("text")
                    if chat_id != str(allowed_chat) or not isinstance(text, str):
                        continue
                    stripped = text.strip()
                    if stripped.startswith("/") or stripped in {"도움말", "메뉴", "?"}:
                        _SESSIONS.pop(chat_id, None)
                        if stripped in {"/add", "메뉴", "/메뉴", "/menu", "/start"}:
                            if stripped == "/add":
                                _set_session(chat_id, "add_name")
                                await _send(
                                    client,
                                    token,
                                    chat_id,
                                    "➕ 감시할 상품/키워드를 입력해주세요.\n예: RX 9070 XT",
                                )
                            else:
                                await _send(
                                    client,
                                    token,
                                    chat_id,
                                    "🛒 sale_bot 관리 메뉴",
                                    _menu_keyboard(),
                                )
                            continue
                        reply = await handle_command(stripped)
                        markup = (
                            _menu_keyboard()
                            if stripped in {"/help", "/도움말", "/?"}
                            else None
                        )
                        await _send(client, token, chat_id, reply, markup)
                        continue

                    session = _SESSIONS.get(chat_id)
                    if session and await _handle_session_text(
                        client,
                        token,
                        chat_id,
                        stripped,
                        session,
                    ):
                        continue
                    await _send(
                        client,
                        token,
                        chat_id,
                        "원하는 작업을 버튼으로 선택해주세요.",
                        _menu_keyboard(),
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"[telegram-admin] error: {exc}")
                await asyncio.sleep(5)
