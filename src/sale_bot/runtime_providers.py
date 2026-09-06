import asyncio
import time
from dataclasses import dataclass

import httpx

from . import providers as legacy
from .cache import BoundedTTLCache
from .models import Listing, Watch
from .providers import BunjangProvider, JoongnaProvider, Provider, daangn_all_scope

# Keep Daangn's process-global broad-region cache bounded on long-running servers.
legacy._SCOPE_DISCOVERY_CACHE = BoundedTTLCache(maxsize=100, ttl_seconds=6 * 60 * 60)


@dataclass(slots=True)
class RegionValidation:
    canonical: str
    target_count: int
    broad: bool


class DaangnRuntimeProvider(legacy.DaangnProvider):
    """Daangn provider with bounded caches, request pacing and region validation."""

    def __init__(self, timeout: int = 20, min_request_interval: float = 1.2):
        super().__init__(timeout)
        self._region_cache = BoundedTTLCache(maxsize=500, ttl_seconds=6 * 60 * 60)
        self._candidate_cache = BoundedTTLCache(maxsize=300, ttl_seconds=6 * 60 * 60)
        self._min_request_interval = max(0.5, float(min_request_interval))
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._backoff_until = 0.0
        self._backoff_seconds = 0.0

    async def _paced_get(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        async with self._request_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at
            pace_delay = self._min_request_interval - elapsed
            backoff_delay = self._backoff_until - now
            delay = max(0.0, pace_delay, backoff_delay)
            if delay > 0:
                await asyncio.sleep(delay)
            response = await self.client.get(url, params=params)
            self._last_request_at = time.monotonic()
            if response.status_code in {403, 429} or 500 <= response.status_code < 600:
                retry_after = response.headers.get("Retry-After")
                try:
                    requested_backoff = float(retry_after) if retry_after else 0.0
                except ValueError:
                    requested_backoff = 0.0
                doubled = self._backoff_seconds * 2 or 5.0
                self._backoff_seconds = min(
                    120.0,
                    max(requested_backoff, 5.0, doubled),
                )
                self._backoff_until = time.monotonic() + self._backoff_seconds
            else:
                self._backoff_seconds = 0.0
                self._backoff_until = 0.0
            return response

    async def _region_candidates(self, keyword: str) -> list[dict]:
        keyword = keyword.strip()
        cached = self._candidate_cache.get(keyword)
        if cached is not None:
            return cached
        response = await self._paced_get(
            "https://www.daangn.com/kr/api/v1/regions/keyword",
            params={"keyword": keyword},
        )
        response.raise_for_status()
        locations = [
            item for item in (response.json().get("locations") or []) if isinstance(item, dict)
        ]
        self._candidate_cache[keyword] = locations
        return locations

    async def _fetch_articles(self, watch: Watch, region_name: str | None) -> list[dict]:
        params: dict[str, str] = {
            "search": watch.query,
            "only_on_sale": "true",
            "_data": "routes/kr.buy-sell._index",
        }
        path = "/kr/buy-sell/"
        if region_name:
            region = await self._resolve_region(region_name)
            path = "/kr/buy-sell/all/"
            params["in"] = f"{region['name']}-{region['id']}"
        response = await self._paced_get(f"https://www.daangn.com{path}", params=params)
        response.raise_for_status()
        payload = response.json()
        all_page = payload.get("allPage")
        if not isinstance(all_page, dict):
            raise TypeError("Daangn search payload shape changed: allPage missing")
        articles = all_page.get("fleamarketArticles")
        if not isinstance(articles, list):
            raise TypeError("Daangn search payload shape changed: fleamarketArticles missing")
        return [article for article in articles if isinstance(article, dict)]

    async def search_region(self, watch: Watch, region_name: str | None) -> list[Listing]:
        return self._parse_articles(await self._fetch_articles(watch, region_name))

    async def validate_region_input(self, value: str) -> RegionValidation:
        requested = " ".join(value.strip().split())
        if not requested:
            raise ValueError("지역을 입력해주세요.")

        scope = daangn_all_scope(requested)
        broad = scope is not None
        if scope is None:
            leaf = legacy._region_leaf(requested)
            # 시/군/구까지만 입력하면 해당 행정구역 전체로 해석합니다.
            broad = leaf.endswith(("시", "군", "구", "자치구"))
            scope = requested if broad else None

        if broad and scope:
            regions = await self._discover_scope_regions(scope)
            if not regions:
                raise RuntimeError(f"Daangn broad region not found: {requested}")
            canonical = requested if daangn_all_scope(requested) else f"{requested} 전체"
            return RegionValidation(canonical=canonical, target_count=len(regions), broad=True)

        selected = await self._resolve_region(requested)
        canonical = legacy._region_label(selected).replace(" > ", " ")
        return RegionValidation(canonical=canonical, target_count=1, broad=False)


def build_runtime_providers(timeout: int) -> dict[str, Provider]:
    return {
        "daangn": DaangnRuntimeProvider(timeout),
        "joongna": JoongnaProvider(timeout),
        "bunjang": BunjangProvider(timeout),
    }
