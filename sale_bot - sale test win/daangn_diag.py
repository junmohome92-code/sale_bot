import asyncio
import re
from dataclasses import replace
from pathlib import Path

import yaml

from sale_bot.models import Watch
from sale_bot.providers import CHEONGJU_ALL, CHEONGJU_NEIGHBORHOODS, DaangnProvider

ROOT = Path(__file__).resolve().parent


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


def _load_watch_and_batches() -> tuple[Watch, int]:
    config_path = ROOT / "config.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    watches = raw.get("watches") or []
    for item in watches:
        if "daangn" in (item.get("providers") or []):
            batches = max(1, min(10, int(raw.get("daangn_full_region_batches", 5))))
            return Watch(**item), batches
    raise RuntimeError("config.yaml에서 daangn provider가 포함된 감시 항목을 찾지 못했습니다.")


def _resolved_label(region: dict) -> str:
    parts: list[str] = []
    for key in ("name1", "name2", "name3", "name"):
        value = region.get(key)
        if value and str(value) not in parts:
            parts.append(str(value))
    return " > ".join(parts) or "(이름 없음)"


async def main() -> None:
    watch, batch_count = _load_watch_and_batches()
    watch.daangn_batch_count = batch_count
    watch.daangn_batch_index = 0
    regions = watch.daangn_regions
    provider = DaangnProvider(timeout=20)
    targets = provider.region_targets(watch)

    print("=" * 62)
    print("당근 진단 - DB/알림에는 아무것도 기록하지 않습니다.")
    print("=" * 62)
    print(f"감시명: {watch.name}")
    print(f"기본 검색어: {watch.query}")
    print(f"설정 지역: {', '.join(regions) if regions else '미지정'}")
    if CHEONGJU_ALL in regions:
        print(
            f"청주시 전체: {len(CHEONGJU_NEIGHBORHOODS)}개 읍/면/동을 "
            f"{batch_count}개 batch로 순환"
        )
        print("진단에서는 요청량을 줄이기 위해 batch 1만 검사합니다.")
    print()

    try:
        if targets != [None]:
            print("[1] 이번 진단 대상 지역 해석 결과")
            for requested in targets:
                if requested is None:
                    continue
                try:
                    resolved = await provider._resolve_region(requested)
                except Exception as exc:  # noqa: BLE001 - diagnostic should continue
                    print(f"- 요청={requested} -> ERROR: {exc}")
                    continue
                print(
                    f"- 요청={requested} -> {_resolved_label(resolved)} "
                    f"| id={resolved.get('id')} depth={resolved.get('depth')}"
                )
            print()

        print("[2] 검색어별 raw 결과")
        for query in _query_variants(watch.query):
            probe_watch = replace(watch, query=query)
            print(f"\n검색어: {query}")
            total = 0
            for region_name in targets:
                label = region_name or "지역 미지정"
                try:
                    articles = await provider._fetch_articles(probe_watch, region_name)
                except Exception as exc:  # noqa: BLE001 - diagnostic should continue
                    print(f"  - {label}: ERROR: {exc}")
                    continue
                total += len(articles)
                print(f"  - {label}: raw={len(articles)}")
                for article in articles[:3]:
                    region_data = article.get("region") or {}
                    article_region = (
                        region_data.get("name") if isinstance(region_data, dict) else None
                    )
                    print(
                        "      "
                        f"{article.get('title')} | {article.get('price')}원 | "
                        f"{article_region or '-'}"
                    )
            print(f"  합계(raw, 지역 중복 포함): {total}")

        print("\n[3] 참고")
        print("- '청주시 전체'는 실제 계속 실행에서 batch가 매 cycle 순환합니다.")
        print("- 단순 동명이 여러 후보면 자동 첫 후보 선택 대신 ambiguous 오류가 납니다.")
        print("- 타지역 동명이 있으면 '대전광역시 유성구 봉명동'처럼 전체 경로를 쓰세요.")
        print("- 기본 검색어만 0이고 다른 검색어가 나오면 검색어 문제입니다.")
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
