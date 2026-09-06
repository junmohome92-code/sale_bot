from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"pattern not found in {path}: {old[:120]!r}")
    text = text.replace(old, new, 1)
    file_path.write_text(text, encoding="utf-8")


# models.py: explicit transaction intent filters.
replace_once(
    "src/sale_bot/models.py",
    'MAX_DAANGN_REGION_SPECS = 10\n',
    '''MAX_DAANGN_REGION_SPECS = 10\n\n_BUYING_INTENT_RE = re.compile(\n    r"삽니다|구합니다|구해요|구함|구매\\s*(?:합니다|해요|원합니다|원해요)|"\n    r"매입\\s*(?:합니다|해요|원합니다|원해요)",\n    re.IGNORECASE,\n)\n_SELLING_INTENT_RE = re.compile(\n    r"팝니다|팔아요|판매\\s*(?:합니다|해요|중)|처분\\s*(?:합니다|해요)",\n    re.IGNORECASE,\n)\n\n\ndef transaction_intent(title: str) -> Literal["buying", "selling", "unknown"]:\n    \"\"\"Classify obvious transaction-intent phrases in a listing title.\"\"\"\n    if _BUYING_INTENT_RE.search(title):\n        return "buying"\n    if _SELLING_INTENT_RE.search(title):\n        return "selling"\n    return "unknown"\n''',
)
replace_once(
    "src/sale_bot/models.py",
    '    ignore_price_at_or_below: int = 0\n    exclude_keywords: list[str] = field(default_factory=list)\n',
    '    ignore_price_at_or_below: int = 0\n    exclude_buying_posts: bool = True\n    exclude_selling_posts: bool = False\n    exclude_keywords: list[str] = field(default_factory=list)\n',
)
replace_once(
    "src/sale_bot/models.py",
    '''    def matches(self, listing: Listing) -> bool:\n        title = listing.title.casefold()\n        if any(word.casefold() in title for word in self.exclude_keywords):\n            return False\n''',
    '''    def matches(self, listing: Listing) -> bool:\n        title = listing.title.casefold()\n        intent = transaction_intent(listing.title)\n        if self.exclude_buying_posts and intent == "buying":\n            return False\n        if self.exclude_selling_posts and intent == "selling":\n            return False\n        if any(word.casefold() in title for word in self.exclude_keywords):\n            return False\n''',
)

# storage.py: schema v4, persistence, defaults, toggles.
replace_once("src/sale_bot/storage.py", "SCHEMA_VERSION = 3\n", "SCHEMA_VERSION = 4\n")
replace_once(
    "src/sale_bot/storage.py",
    '''              ignore_price_at_or_below INTEGER NOT NULL DEFAULT 0,\n              exclude_keywords TEXT NOT NULL DEFAULT '[]',\n''',
    '''              ignore_price_at_or_below INTEGER NOT NULL DEFAULT 0,\n              exclude_buying_posts INTEGER NOT NULL DEFAULT 1,\n              exclude_selling_posts INTEGER NOT NULL DEFAULT 0,\n              exclude_keywords TEXT NOT NULL DEFAULT '[]',\n''',
)
replace_once(
    "src/sale_bot/storage.py",
    '''        if "ignore_price_at_or_below" not in columns:\n            self.conn.execute(\n                "ALTER TABLE managed_watches ADD COLUMN "\n                "ignore_price_at_or_below INTEGER NOT NULL DEFAULT 0"\n            )\n''',
    '''        if "ignore_price_at_or_below" not in columns:\n            self.conn.execute(\n                "ALTER TABLE managed_watches ADD COLUMN "\n                "ignore_price_at_or_below INTEGER NOT NULL DEFAULT 0"\n            )\n        if "exclude_buying_posts" not in columns:\n            self.conn.execute(\n                "ALTER TABLE managed_watches ADD COLUMN "\n                "exclude_buying_posts INTEGER NOT NULL DEFAULT 1"\n            )\n        if "exclude_selling_posts" not in columns:\n            self.conn.execute(\n                "ALTER TABLE managed_watches ADD COLUMN "\n                "exclude_selling_posts INTEGER NOT NULL DEFAULT 0"\n            )\n''',
)
replace_once(
    "src/sale_bot/storage.py",
    '''                (name,query,min_price,max_price,ignore_price_at_or_below,exclude_keywords,providers,daangn_region,created_at)\n                VALUES (?,?,?,?,?,?,?,?,?)\"\"\",\n''',
    '''                (name,query,min_price,max_price,ignore_price_at_or_below,exclude_buying_posts,exclude_selling_posts,exclude_keywords,providers,daangn_region,created_at)\n                VALUES (?,?,?,?,?,?,?,?,?,?,?)\"\"\",\n''',
)
replace_once(
    "src/sale_bot/storage.py",
    '''                    watch.ignore_price_at_or_below,\n                    json.dumps(watch.exclude_keywords, ensure_ascii=False),\n''',
    '''                    watch.ignore_price_at_or_below,\n                    int(watch.exclude_buying_posts),\n                    int(watch.exclude_selling_posts),\n                    json.dumps(watch.exclude_keywords, ensure_ascii=False),\n''',
)
replace_once(
    "src/sale_bot/storage.py",
    '''            ignore_price_at_or_below=int(row["ignore_price_at_or_below"] or 0),\n            exclude_keywords=json.loads(row["exclude_keywords"]),\n''',
    '''            ignore_price_at_or_below=int(row["ignore_price_at_or_below"] or 0),\n            exclude_buying_posts=bool(row["exclude_buying_posts"]),\n            exclude_selling_posts=bool(row["exclude_selling_posts"]),\n            exclude_keywords=json.loads(row["exclude_keywords"]),\n''',
)
replace_once(
    "src/sale_bot/storage.py",
    '''        ignore_price_at_or_below: int = 0,\n        query: str | None = None,\n''',
    '''        ignore_price_at_or_below: int = 0,\n        exclude_buying_posts: bool = True,\n        exclude_selling_posts: bool = False,\n        query: str | None = None,\n''',
)
replace_once(
    "src/sale_bot/storage.py",
    '''            (name,query,min_price,max_price,ignore_price_at_or_below,exclude_keywords,providers,daangn_region,created_at)\n            VALUES (?,?,?,?,?,?,?,?,?)\"\"\",\n''',
    '''            (name,query,min_price,max_price,ignore_price_at_or_below,exclude_buying_posts,exclude_selling_posts,exclude_keywords,providers,daangn_region,created_at)\n            VALUES (?,?,?,?,?,?,?,?,?,?,?)\"\"\",\n''',
)
replace_once(
    "src/sale_bot/storage.py",
    '''                ignore_price_at_or_below,\n                json.dumps(exclude_keywords or [], ensure_ascii=False),\n''',
    '''                ignore_price_at_or_below,\n                int(exclude_buying_posts),\n                int(exclude_selling_posts),\n                json.dumps(exclude_keywords or [], ensure_ascii=False),\n''',
)
replace_once(
    "src/sale_bot/storage.py",
    '''    def reset_watch_tracking(self, watch_id: int) -> None:\n''',
    '''    def set_transaction_filters(\n        self,\n        watch_id: int,\n        *,\n        exclude_buying_posts: bool,\n        exclude_selling_posts: bool,\n    ) -> bool:\n        cur = self.conn.execute(\n            "UPDATE managed_watches "\n            "SET exclude_buying_posts=?, exclude_selling_posts=? WHERE id=?",\n            (int(exclude_buying_posts), int(exclude_selling_posts), watch_id),\n        )\n        self.conn.commit()\n        return cur.rowcount > 0\n\n    def reset_watch_tracking(self, watch_id: int) -> None:\n''',
)

# admin.py: show/toggle transaction filters from Telegram.
replace_once(
    "src/sale_bot/admin.py",
    "• 슬롯별로 'N원 이하 무시' 가격을 설정할 수 있음\n",
    "• 슬롯별로 'N원 이하 무시' 가격을 설정할 수 있음\n• 삽니다/팝니다 글을 각각 제외 또는 허용할 수 있음\n",
)
replace_once(
    "src/sale_bot/admin.py",
    '''def _format_ignore_price(value: int) -> str:\n    return "사용 안 함" if value <= 0 else f"{value:,}원 이하 무시"\n\n\n''',
    '''def _format_ignore_price(value: int) -> str:\n    return "사용 안 함" if value <= 0 else f"{value:,}원 이하 무시"\n\n\ndef _format_transaction_filters(watch: Watch) -> str:\n    buying = "삽니다 제외" if watch.exclude_buying_posts else "삽니다 허용"\n    selling = "팝니다 제외" if watch.exclude_selling_posts else "팝니다 허용"\n    return f"{buying} · {selling}"\n\n\n''',
)
replace_once(
    "src/sale_bot/admin.py",
    '''            f"  🚫 무시가격: {_format_ignore_price(watch.ignore_price_at_or_below)}\\n"\n            f"  📍 당근: {daangn_region}\\n"\n''',
    '''            f"  🚫 무시가격: {_format_ignore_price(watch.ignore_price_at_or_below)}\\n"\n            f"  🧾 거래유형: {_format_transaction_filters(watch)}\\n"\n            f"  📍 당근: {daangn_region}\\n"\n''',
)
replace_once(
    "src/sale_bot/admin.py",
    '''def _watch_keyboard(watch_id: int, enabled: bool) -> dict:\n    toggle = "pause" if enabled else "resume"\n    toggle_text = "⏸ 일시정지" if enabled else "▶️ 재개"\n''',
    '''def _watch_keyboard(\n    watch_id: int,\n    enabled: bool,\n    exclude_buying_posts: bool = True,\n    exclude_selling_posts: bool = False,\n) -> dict:\n    toggle = "pause" if enabled else "resume"\n    toggle_text = "⏸ 일시정지" if enabled else "▶️ 재개"\n    buying_text = "✅ 삽니다 제외" if exclude_buying_posts else "⬜ 삽니다 허용"\n    selling_text = "✅ 팝니다 제외" if exclude_selling_posts else "⬜ 팝니다 허용"\n''',
)
replace_once(
    "src/sale_bot/admin.py",
    '''            ],\n            [{"text": "📍 지역 변경", "callback_data": f"watch:region:{watch_id}"}],\n''',
    '''            ],\n            [\n                {"text": buying_text, "callback_data": f"watch:buying:{watch_id}"},\n                {"text": selling_text, "callback_data": f"watch:selling:{watch_id}"},\n            ],\n            [{"text": "📍 지역 변경", "callback_data": f"watch:region:{watch_id}"}],\n''',
)
replace_once(
    "src/sale_bot/admin.py",
    '''            f"🚫 무시가격: {_format_ignore_price(session.data['ignore_price_at_or_below'])}\\n"\n            f"📍 당근: {region_text}\\n"\n''',
    '''            f"🚫 무시가격: {_format_ignore_price(session.data['ignore_price_at_or_below'])}\\n"\n            "🧾 거래유형: 삽니다 제외 · 팝니다 허용\\n"\n            f"📍 당근: {region_text}\\n"\n''',
)
replace_once(
    "src/sale_bot/admin.py",
    '''                    f"🚫 무시가격: {_format_ignore_price(watch.ignore_price_at_or_below)}\\n"\n                    f"📍 당근: {region}\\n"\n''',
    '''                    f"🚫 무시가격: {_format_ignore_price(watch.ignore_price_at_or_below)}\\n"\n                    f"🧾 거래유형: {_format_transaction_filters(watch)}\\n"\n                    f"📍 당근: {region}\\n"\n''',
)
replace_once(
    "src/sale_bot/admin.py",
    '''                await _send(client, token, chat_id, detail, _watch_keyboard(watch_id, enabled))\n''',
    '''                await _send(\n                    client,\n                    token,\n                    chat_id,\n                    detail,\n                    _watch_keyboard(\n                        watch_id,\n                        enabled,\n                        watch.exclude_buying_posts,\n                        watch.exclude_selling_posts,\n                    ),\n                )\n''',
)
replace_once(
    "src/sale_bot/admin.py",
    '''            elif action == "region":\n''',
    '''            elif action in {"buying", "selling"}:\n                item = store.get_watch(watch_id)\n                if item is None:\n                    await _send(client, token, chat_id, "이미 삭제된 슬롯입니다.")\n                    return\n                watch, enabled = item\n                exclude_buying = watch.exclude_buying_posts\n                exclude_selling = watch.exclude_selling_posts\n                if action == "buying":\n                    exclude_buying = not exclude_buying\n                else:\n                    exclude_selling = not exclude_selling\n                store.set_transaction_filters(\n                    watch_id,\n                    exclude_buying_posts=exclude_buying,\n                    exclude_selling_posts=exclude_selling,\n                )\n                store.reset_watch_tracking(watch_id)\n                updated = store.get_watch(watch_id)\n                assert updated is not None\n                updated_watch, _ = updated\n                request_scan()\n                await _send(\n                    client,\n                    token,\n                    chat_id,\n                    "✅ 거래유형 설정 변경\\n"\n                    f"🧾 {_format_transaction_filters(updated_watch)}\\n"\n                    "조건을 다시 적용하기 위해 첫 검색을 새로 시작합니다.",\n                    _watch_keyboard(\n                        watch_id,\n                        enabled,\n                        updated_watch.exclude_buying_posts,\n                        updated_watch.exclude_selling_posts,\n                    ),\n                )\n\n            elif action == "region":\n''',
)

# Config example: document fresh-watch defaults.
replace_once(
    "config.example.yaml",
    "#     ignore_price_at_or_below: 10000\n",
    "#     ignore_price_at_or_below: 10000\n#     exclude_buying_posts: true\n#     exclude_selling_posts: false\n",
)

# Tests.
replace_once(
    "tests/test_core.py",
    '        assert version == "3"\n',
    '        assert version == "4"\n',
)
replace_once(
    "tests/test_core.py",
    '''def test_twenty_watch_slots(tmp_path):\n''',
    '''def test_transaction_type_filters_default_to_buying_only():\n    watch = Watch(name="switch2", query="switch2", max_price=1_000_000)\n    assert not watch.matches(\n        Listing("joongna", "buy-1", "닌텐도 스위치2 삽니다", 600_000, "https://x")\n    )\n    assert not watch.matches(\n        Listing("joongna", "buy-2", "닌텐도 스위치2 구합니다", 600_000, "https://x")\n    )\n    assert watch.matches(\n        Listing("joongna", "sell-1", "닌텐도 스위치2 팝니다", 600_000, "https://x")\n    )\n\n    watch.exclude_buying_posts = False\n    watch.exclude_selling_posts = True\n    assert watch.matches(\n        Listing("joongna", "buy-3", "닌텐도 스위치2 구매합니다", 600_000, "https://x")\n    )\n    assert not watch.matches(\n        Listing("joongna", "sell-2", "닌텐도 스위치2 판매합니다", 600_000, "https://x")\n    )\n\n\ndef test_twenty_watch_slots(tmp_path):\n''',
)
replace_once(
    "tests/test_market_api_and_price_floor.py",
    '''        assert "ignore_price_at_or_below" in columns\n''',
    '''        assert "ignore_price_at_or_below" in columns\n        assert "exclude_buying_posts" in columns\n        assert "exclude_selling_posts" in columns\n''',
)
replace_once(
    "tests/test_market_api_and_price_floor.py",
    '''        assert watch.ignore_price_at_or_below == 20_000\n''',
    '''        assert watch.ignore_price_at_or_below == 20_000\n        assert watch.exclude_buying_posts is True\n        assert watch.exclude_selling_posts is False\n        assert store.set_transaction_filters(\n            watch_id, exclude_buying_posts=False, exclude_selling_posts=True\n        )\n        watch, _ = store.get_watch(watch_id)\n        assert watch.exclude_buying_posts is False\n        assert watch.exclude_selling_posts is True\n''',
)
replace_once(
    "tests/test_market_api_and_price_floor.py",
    '''    assert "🚫 무시가격" in labels\n''',
    '''    assert "🚫 무시가격" in labels\n    assert "✅ 삽니다 제외" in labels\n    assert "⬜ 팝니다 허용" in labels\n''',
)

print("transaction filter patch applied")
