import argparse
import asyncio
import re
from dataclasses import replace
from pathlib import Path

import yaml

from sale_bot.models import Watch
from sale_bot.providers import DaangnProvider, daangn_all_scope

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
            raw_batches = raw.get(
                "daangn_region_batches",
                raw.get("daangn_full_region_batches", 5),
            )
            batches = max(1, min(20, int(raw_batches)))
            return Watch(**item), batches
    raise RuntimeError("config.yaml에서 daangn provider가 포함된 감시 항목을 찾지 못했습니다.")


def _resolved_label(region: dict) -> str:
    parts: list[str] = []
    for key in ("name1", "name2", "name3", "name"):
        value = region.get(key)
        if value and str(value) not in parts:
            parts.append(str(value))
    return " > ".join(parts) or "(이름 없음)"


def _print_scope_summary(provider: DaangnProvider) -> None:
    if not provider.last_scope_expansions:
        return
    print("[0] '전체' 지역 자동 확장 결과")
    for spec, labels in provider.last_scope_expansions.items():
        groups = sorted(
            {
                " / ".join(label.split(" ")[:-1])
                for label in labels
                if len(label.split(" ")) >= 2
            }
        )
        print(f"- {spec}: 당근 검색 가능 하위지역 {len(labels)}개")
        if groups:
            preview = ", ".join(groups[:8])
            suffix = " ..." if len(groups) > 8 else ""
            print(f"  상위 지역: {preview}{suffix}")
    print()


async def main(*, all_regions: bool = False) -> None:
    watch, batch_count = _load_watch_and_batches()
    watch.daangn_batch_count = batch_count
    watch.daangn_batch_index = 0
    provider = DaangnProvider(timeout=20)

    print("=" * 62)
    if all_regions:
        print("당근 전체지역 검증 - 검색 매물/DB/알림에는 아무것도 기록하지 않습니다.")
    else:
        print("당근 진단 - DB/알림에는 아무것도 기록하지 않습니다.")
    print("=" * 62)
    print(f"감시명: {watch.name}")
    print(f"기본 검색어: {watch.query}")
    print(f"설정 지역: {', '.join(watch.daangn_regions) if watch.daangn_regions else '미지정'}")

    broad_specs = [region for region in watch.daangn_regions if daangn_all_scope(region)]
    if broad_specs:
        print(f"'전체' 지역은 {batch_count}개 batch로 나눠 순환합니다.")
        if not all_regions:
            print("이번 진단에서는 batch 1만 실제 검색합니다.")
    print()

    try:
        targets = (
            await provider.all_region_targets(watch)
            if all_regions
            else await provider.region_targets(watch)
        )
        _print_scope_summary(provider)

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
            if errors:
                print("- 오류가 있으면 해당 지역명을 그대로 보내주세요.")
            else:
                print("- 현재 발견된 전체 하위지역이 모두 당근 region id로 정상 해석됩니다.")
            return

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
        print("- 'OO시 전체', 'OO구 전체'는 당근의 현재 지역 계층을 자동 발견합니다.")
        print("- 실제 계속 실행에서는 설정된 batch가 매 cycle 순환합니다.")
        print("- 동명이 여러 후보면 자동 첫 후보 선택 대신 ambiguous 오류가 납니다.")
        print("- 개별 동명이 겹치면 '대전광역시 유성구 봉명동'처럼 전체 경로를 쓰세요.")
        print("- 메뉴의 전체지역 검증은 매물 검색 없이 지역 해석만 전수 확인합니다.")
    finally:
        await provider.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-regions", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(all_regions=args.all_regions))
