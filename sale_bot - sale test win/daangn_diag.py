import argparse
import asyncio
import re
from dataclasses import replace
from pathlib import Path

import yaml

from sale_bot.models import Watch
from sale_bot.runtime_providers import DaangnRuntimeProvider
from sale_bot.storage import Store

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "sale_bot-win.sqlite3"


def _query_variants(query: str) -> list[str]:
    variants = [query.strip()]
    compact = re.sub(r"\s+", "", query)
    if compact and compact not in variants:
        variants.append(compact)
    tokens = re.findall(r"[0-9A-Za-z가-힣]+", query)
    digit_tokens = [token for token in tokens if any(char.isdigit() for char in token)]
    if digit_tokens:
        broad = max(digit_tokens, key=len)
        if broad not in variants:
            variants.append(broad)
    return variants


def _load_watch() -> Watch:
    if DB_PATH.exists():
        store = Store(DB_PATH)
        try:
            for _, watch, enabled in store.list_watches():
                if enabled and "daangn" in watch.providers:
                    return watch
        finally:
            store.close()

    config_path = ROOT / "config.yaml"
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        for item in raw.get("watches") or []:
            if "daangn" in (item.get("providers") or []):
                return Watch(**item)
    raise RuntimeError(
        "당근 감시 슬롯이 없습니다. Telegram /menu에서 슬롯을 추가하거나 "
        "Windows config.yaml의 최초 seed를 설정해주세요."
    )


def _resolved_label(region: dict) -> str:
    parts: list[str] = []
    for key in ("name1", "name2", "name3", "name"):
        value = region.get(key)
        if value and str(value) not in parts:
            parts.append(str(value))
    return " > ".join(parts) or "(이름 없음)"


async def main(*, all_regions: bool = False) -> None:
    watch = _load_watch()
    provider = DaangnRuntimeProvider(timeout=20)

    print("=" * 62)
    if all_regions:
        print("당근 전체지역 검증 - 매물/DB/알림에는 아무것도 기록하지 않습니다.")
    else:
        print("당근 샘플 진단 - 최대 5개 지역만 매물 검색합니다.")
    print("=" * 62)
    print(f"감시명: {watch.name}")
    print(f"검색어: {watch.query}")
    print(f"설정 지역: {', '.join(watch.daangn_regions) if watch.daangn_regions else '미지정'}")
    print()

    try:
        targets = await provider.all_region_targets(watch)
        print("[1] 지역 해석 결과")
        errors = 0
        for requested in targets:
            if requested is None:
                print("- 지역 미지정")
                continue
            try:
                resolved = await provider._resolve_region(requested)
            except Exception as exc:  # noqa: BLE001 - diagnostic should continue
                errors += 1
                print(f"- 요청={requested} -> ERROR: {exc}")
                continue
            print(
                f"- 요청={requested} -> {_resolved_label(resolved)} "
                f"| id={resolved.get('id')} depth={resolved.get('depth')}"
            )
        print()

        if all_regions:
            print("[2] 전체지역 검증 요약")
            print(f"- 대상={len(targets)} / 성공={len(targets) - errors} / 오류={errors}")
            return

        print("[2] 검색어별 raw 결과 (앞 5개 지역)")
        sample_targets = targets[:5]
        for query in _query_variants(watch.query):
            probe_watch = replace(watch, query=query)
            print(f"\n검색어: {query}")
            total = 0
            for region_name in sample_targets:
                label = region_name or "지역 미지정"
                try:
                    listings = await provider.search_region(probe_watch, region_name)
                except Exception as exc:  # noqa: BLE001
                    print(f"  - {label}: ERROR: {exc}")
                    continue
                total += len(listings)
                print(f"  - {label}: parsed={len(listings)}")
                for listing in listings[:3]:
                    print(f"      {listing.title} | {listing.price}원 | {listing.location or '-'}")
            print(f"  합계(지역 중복 가능): {total}")

        print("\n[3] 참고")
        print("- 시/군/구 입력은 Telegram 등록 시 실제 당근 지역으로 먼저 검증됩니다.")
        print("- 실제 운영은 batch 수를 직접 정하지 않고 전체 대상 작업을 안전 간격으로 순환합니다.")
        print("- 동명이면 상위 지역을 포함해 입력하세요. 예: 대전시 유성구 봉명동")
    finally:
        await provider.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-regions", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(all_regions=args.all_regions))
