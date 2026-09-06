from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, got {count}: {old[:80]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# storage.py: schema v3 + persistent per-watch ignored low-price floor.
path = "src/sale_bot/storage.py"
replace_once(path, "SCHEMA_VERSION = 2", "SCHEMA_VERSION = 3")
replace_once(
    path,
    "              max_price INTEGER NOT NULL,\n              exclude_keywords TEXT NOT NULL DEFAULT '[]',",
    "              max_price INTEGER NOT NULL,\n"
    "              ignore_price_at_or_below INTEGER NOT NULL DEFAULT 0,\n"
    "              exclude_keywords TEXT NOT NULL DEFAULT '[]',",
)
replace_once(
    path,
    '        if "min_price" not in columns:\n            self.conn.execute("ALTER TABLE managed_watches ADD COLUMN min_price INTEGER")',
    '        if "min_price" not in columns:\n'
    '            self.conn.execute("ALTER TABLE managed_watches ADD COLUMN min_price INTEGER")\n'
    '        if "ignore_price_at_or_below" not in columns:\n'
    '            self.conn.execute(\n'
    '                "ALTER TABLE managed_watches ADD COLUMN "\n'
    '                "ignore_price_at_or_below INTEGER NOT NULL DEFAULT 0"\n'
    '            )',
)
replace_once(
    path,
    "                (name,query,min_price,max_price,exclude_keywords,providers,daangn_region,created_at)\n"
    "                VALUES (?,?,?,?,?,?,?,?)",
    "                (name,query,min_price,max_price,ignore_price_at_or_below,exclude_keywords,providers,daangn_region,created_at)\n"
    "                VALUES (?,?,?,?,?,?,?,?,?)",
)
replace_once(
    path,
    "                    watch.max_price,\n                    json.dumps(watch.exclude_keywords, ensure_ascii=False),",
    "                    watch.max_price,\n                    watch.ignore_price_at_or_below,\n"
    "                    json.dumps(watch.exclude_keywords, ensure_ascii=False),",
)
replace_once(
    path,
    "            max_price=int(row[\"max_price\"]),\n            exclude_keywords=json.loads(row[\"exclude_keywords\"]),",
    "            max_price=int(row[\"max_price\"]),\n"
    "            ignore_price_at_or_below=int(row[\"ignore_price_at_or_below\"] or 0),\n"
    "            exclude_keywords=json.loads(row[\"exclude_keywords\"]),",
)
replace_once(
    path,
    "        min_price: int | None = None,\n        query: str | None = None,",
    "        min_price: int | None = None,\n        ignore_price_at_or_below: int = 0,\n        query: str | None = None,",
)
replace_once(
    path,
    "        if min_price is not None and min_price > max_price:\n            raise ValueError(\"min_price cannot exceed max_price\")\n        count = int(",
    "        if min_price is not None and min_price > max_price:\n"
    "            raise ValueError(\"min_price cannot exceed max_price\")\n"
    "        if ignore_price_at_or_below < 0:\n"
    "            raise ValueError(\"ignore_price_at_or_below cannot be negative\")\n"
    "        count = int(",
)
replace_once(
    path,
    "            (name,query,min_price,max_price,exclude_keywords,providers,daangn_region,created_at)\n"
    "            VALUES (?,?,?,?,?,?,?,?)",
    "            (name,query,min_price,max_price,ignore_price_at_or_below,exclude_keywords,providers,daangn_region,created_at)\n"
    "            VALUES (?,?,?,?,?,?,?,?,?)",
)
replace_once(
    path,
    "                max_price,\n                json.dumps(exclude_keywords or [], ensure_ascii=False),",
    "                max_price,\n                ignore_price_at_or_below,\n"
    "                json.dumps(exclude_keywords or [], ensure_ascii=False),",
)
replace_once(
    path,
    "    def set_region(self, watch_id: int, region: str | list[str] | None) -> bool:\n",
    "    def set_ignore_price_at_or_below(self, watch_id: int, value: int) -> bool:\n"
    "        if value < 0:\n"
    "            raise ValueError(\"ignore_price_at_or_below cannot be negative\")\n"
    "        cur = self.conn.execute(\n"
    "            \"UPDATE managed_watches SET ignore_price_at_or_below=? WHERE id=?\",\n"
    "            (value, watch_id),\n"
    "        )\n"
    "        self.conn.commit()\n"
    "        return cur.rowcount > 0\n\n"
    "    def reset_watch_tracking(self, watch_id: int) -> None:\n"
    "        with self.conn:\n"
    "            for table in (\n"
    "                \"pending_alerts\",\n"
    "                \"watch_price_history\",\n"
    "                \"watch_listing_state\",\n"
    "                \"watch_scan_state\",\n"
    "            ):\n"
    "                self.conn.execute(f\"DELETE FROM {table} WHERE watch_id=?\", (watch_id,))\n\n"
    "    def set_region(self, watch_id: int, region: str | list[str] | None) -> bool:\n",
)

# admin.py: add/edit ignored low-price floor in the button wizard.
path = "src/sale_bot/admin.py"
replace_once(
    path,
    "• 같은 가격 반복 / 가격 상승은 알림 없음\n",
    "• 같은 가격 반복 / 가격 상승은 알림 없음\n"
    "• 슬롯별로 'N원 이하 무시' 가격을 설정할 수 있음\n",
)
replace_once(
    path,
    "def _format_price_range(min_price: int | None, max_price: int | None) -> str:\n",
    "def _parse_nonnegative_price(value: str) -> int:\n"
    "    cleaned = value.replace(\",\", \"\").replace(\"원\", \"\").strip()\n"
    "    parsed = int(cleaned)\n"
    "    if parsed < 0:\n"
    "        raise ValueError(\"price cannot be negative\")\n"
    "    return parsed\n\n\n"
    "def _format_ignore_price(value: int) -> str:\n"
    "    return \"사용 안 함\" if value <= 0 else f\"{value:,}원 이하 무시\"\n\n\n"
    "def _format_price_range(min_price: int | None, max_price: int | None) -> str:\n",
)
replace_once(
    path,
    "            f\"  💰 {_format_price_range(watch.min_price, watch.max_price)}\\n\"\n"
    "            f\"  📍 당근: {daangn_region}\\n\"",
    "            f\"  💰 {_format_price_range(watch.min_price, watch.max_price)}\\n\"\n"
    "            f\"  🚫 무시가격: {_format_ignore_price(watch.ignore_price_at_or_below)}\\n\"\n"
    "            f\"  📍 당근: {daangn_region}\\n\"",
)
replace_once(
    path,
    "            [\n                {\"text\": \"💰 가격 변경\", \"callback_data\": f\"watch:price:{watch_id}\"},\n"
    "                {\"text\": \"📍 지역 변경\", \"callback_data\": f\"watch:region:{watch_id}\"},\n"
    "            ],\n            [{\"text\": toggle_text, \"callback_data\": f\"watch:{toggle}:{watch_id}\"}],",
    "            [\n                {\"text\": \"💰 가격 변경\", \"callback_data\": f\"watch:price:{watch_id}\"},\n"
    "                {\"text\": \"🚫 무시가격\", \"callback_data\": f\"watch:ignore:{watch_id}\"},\n"
    "            ],\n"
    "            [{\"text\": \"📍 지역 변경\", \"callback_data\": f\"watch:region:{watch_id}\"}],\n"
    "            [{\"text\": toggle_text, \"callback_data\": f\"watch:{toggle}:{watch_id}\"}],",
)
replace_once(
    path,
    "        session.data.update(min_price=minimum, max_price=maximum)\n        session.step = \"add_region\"\n        await _send(\n            client,\n            token,\n            chat_id,\n            \"📍 당근 지역을 입력해주세요.\\n\"\n            \"한 곳: 청주시 청원구\\n\"\n            \"여러 곳: 청주시, 세종시\\n\"\n            \"또는: 청주시 청원구, 세종시\\n\\n\"\n            \"중고나라/번개장터는 입력 지역들의 시 단위로 검색합니다.\\n\"\n            \"지역을 쓰지 않으려면 '건너뛰기'를 입력하세요.\",\n        )\n        return True\n\n    if session.step in {\"add_region\", \"edit_region\"}:",
    "        session.data.update(min_price=minimum, max_price=maximum)\n"
    "        session.step = \"add_ignore_price\"\n"
    "        await _send(\n"
    "            client,\n"
    "            token,\n"
    "            chat_id,\n"
    "            \"🚫 무시할 최저가격을 입력해주세요.\\n\"\n"
    "            \"예: 10000 → 10,000원 이하 매물은 무시\\n\"\n"
    "            \"사용하지 않으려면 0을 입력하세요.\",\n"
    "        )\n"
    "        return True\n\n"
    "    if session.step == \"add_ignore_price\":\n"
    "        try:\n"
    "            ignore_price = _parse_nonnegative_price(text)\n"
    "        except (ValueError, TypeError):\n"
    "            await _send(client, token, chat_id, \"❌ 0 이상의 가격을 입력해주세요.\")\n"
    "            return True\n"
    "        session.data[\"ignore_price_at_or_below\"] = ignore_price\n"
    "        session.step = \"add_region\"\n"
    "        await _send(\n"
    "            client,\n"
    "            token,\n"
    "            chat_id,\n"
    "            \"📍 당근 지역을 입력해주세요.\\n\"\n"
    "            \"한 곳: 청주시 청원구\\n\"\n"
    "            \"여러 곳: 청주시, 세종시\\n\"\n"
    "            \"또는: 청주시 청원구, 세종시\\n\\n\"\n"
    "            \"중고나라/번개장터는 입력 지역들의 시 단위로 검색합니다.\\n\"\n"
    "            \"지역을 쓰지 않으려면 '건너뛰기'를 입력하세요.\",\n"
    "        )\n"
    "        return True\n\n"
    "    if session.step in {\"add_region\", \"edit_region\"}:",
)
replace_once(
    path,
    "            f\"💰 {_format_price_range(session.data['min_price'], session.data['max_price'])}\\n\"\n"
    "            f\"📍 당근: {region_text}\\n\"",
    "            f\"💰 {_format_price_range(session.data['min_price'], session.data['max_price'])}\\n\"\n"
    "            f\"🚫 무시가격: {_format_ignore_price(session.data['ignore_price_at_or_below'])}\\n\"\n"
    "            f\"📍 당근: {region_text}\\n\"",
)
replace_once(
    path,
    "    if session.step == \"edit_price\":\n",
    "    if session.step == \"edit_ignore_price\":\n"
    "        try:\n"
    "            ignore_price = _parse_nonnegative_price(text)\n"
    "        except (ValueError, TypeError):\n"
    "            await _send(client, token, chat_id, \"❌ 0 이상의 가격을 입력해주세요.\")\n"
    "            return True\n"
    "        store = Store(_db_path())\n"
    "        try:\n"
    "            watch_id = int(session.data[\"watch_id\"])\n"
    "            if not store.set_ignore_price_at_or_below(watch_id, ignore_price):\n"
    "                await _send(client, token, chat_id, \"이미 삭제된 슬롯입니다.\")\n"
    "                return True\n"
    "            store.reset_watch_tracking(watch_id)\n"
    "        finally:\n"
    "            store.close()\n"
    "        _SESSIONS.pop(chat_id, None)\n"
    "        request_scan()\n"
    "        await _send(\n"
    "            client,\n"
    "            token,\n"
    "            chat_id,\n"
    "            f\"✅ 무시가격 변경: {_format_ignore_price(ignore_price)}\\n\"\n"
    "            \"조건을 다시 적용하기 위해 첫 검색을 새로 시작합니다.\",\n"
    "            _menu_keyboard(),\n"
    "        )\n"
    "        return True\n\n"
    "    if session.step == \"edit_price\":\n",
)
replace_once(
    path,
    "                    f\"💰 {_format_price_range(watch.min_price, watch.max_price)}\\n\"\n"
    "                    f\"📍 당근: {region}\\n\"",
    "                    f\"💰 {_format_price_range(watch.min_price, watch.max_price)}\\n\"\n"
    "                    f\"🚫 무시가격: {_format_ignore_price(watch.ignore_price_at_or_below)}\\n\"\n"
    "                    f\"📍 당근: {region}\\n\"",
)
replace_once(
    path,
    "            if action == \"price\":\n                _set_session(chat_id, \"edit_price\", watch_id=watch_id)\n                await _send(client, token, chat_id, \"💰 새 가격을 입력해주세요.\")\n\n            elif action == \"region\":",
    "            if action == \"price\":\n"
    "                _set_session(chat_id, \"edit_price\", watch_id=watch_id)\n"
    "                await _send(client, token, chat_id, \"💰 새 가격을 입력해주세요.\")\n\n"
    "            elif action == \"ignore\":\n"
    "                _set_session(chat_id, \"edit_ignore_price\", watch_id=watch_id)\n"
    "                await _send(\n"
    "                    client,\n"
    "                    token,\n"
    "                    chat_id,\n"
    "                    \"🚫 새 무시가격을 입력해주세요.\\n\"\n"
    "                    \"예: 10000 → 10,000원 이하 무시\\n\"\n"
    "                    \"0 → 사용 안 함\",\n"
    "                )\n\n"
    "            elif action == \"region\":",
)
replace_once(
    path,
    "                min_price=session.data.get(\"min_price\"),\n            )",
    "                min_price=session.data.get(\"min_price\"),\n"
    "                ignore_price_at_or_below=int(\n"
    "                    session.data.get(\"ignore_price_at_or_below\", 0)\n"
    "                ),\n"
    "            )",
)

# config example: document the persisted seed field.
path = "config.example.yaml"
replace_once(
    path,
    "#     max_price: 1000000\n",
    "#     max_price: 1000000\n#     ignore_price_at_or_below: 10000\n",
)

print("market patch applied")
