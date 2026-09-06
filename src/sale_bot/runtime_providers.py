import asyncio
import time
from dataclasses import dataclass

import httpx

from . import providers as legacy
from .cache import BoundedTTLCache
from .models import Listing, Watch
from .providers import Provider, daangn_all_scope

# Keep Daangn's process-global broad-region cache bounded on long-running servers.
legacy._SCOPE_DISCOVERY_CACHE = BoundedTTLCache(maxsize=100, ttl_seconds=6 * 60 * 60)

JOONGNA_SEARCH_API = "https://search-api.joongna.com/v3/search/all"
BUNJANG_SEARCH_API = "https://api.bunjang.co.kr/api/1/find_v2.json"
JOONGNA_SEARCH_PAGES = 5
JOONGNA_PAGE_SIZE = 50
BUNJANG_SEARCH_PAGES = 5
BUNJANG_PAGE_SIZE = 100


def _first_value(row: dict, *keys: str) -> object | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", []):
            return value
    return None


def _location_text(row: dict) -> str | None:
    value = _first_value(
        row,
        "locationNames",
        "mainLocationName",
        "location",
        "location_name",
        "region",
        "regionName",
        "addressName",
        "sellerLocation",
    )
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return " ".join(parts) or None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


class JoongnaRuntimeProvider(Provider):
    """Current Joongna JSON search API with structured seller location metadata."""

    name = "joongna"

    def __init__(self, timeout: int = 20):
        super().__init__()
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "ko-KR,ko;q=0.9",
                "Origin": "https://web.joongna.com",
                "Referer": "https://web.joongna.com/",
            },
        )

    @staticmethod
    def _rows(payload: dict) -> list[dict]:
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            return []
        candidates = (
            data.get("items"),
            data.get("productList"),
            data.get("products"),
            data.get("list"),
            (data.get("searchResult") or {}).get("items")
            if isinstance(data.get("searchResult"), dict)
            else None,
        )
        for candidate in candidates:
            if isinstance(candidate, list):
                return [row for row in candidate if isinstance(row, dict)]
        return []

    @staticmethod
    def _parse_row(row: dict) -> Listing | None:
        item_id = _first_value(row, "seq", "productSeq", "productId", "articleId", "id")
        title = _first_value(row, "title", "productTitle", "name", "subject")
        if item_id is None or not title:
            return None
        state = row.get("state")
        if isinstance(state, int) and state != 0:
            return None
        price = legacy.coerce_price(
            _first_value(row, "price", "productPrice", "sellPrice", "priceValue")
        )
        image = _first_value(row, "url", "imageUrl", "thumbnail", "image", "thumbImageUrl")
        return Listing(
            "joongna",
            str(item_id),
            str(title).strip(),
            price,
            f"https://web.joongna.com/product/{item_id}",
            location=_location_text(row),
            image_url=str(image) if image else None,
        )

    async def search(self, watch: Watch) -> list[Listing]:
        self.last_search_complete = True
        self.last_search_errors = []
        results: dict[str, Listing] = {}
        for page in range(JOONGNA_SEARCH_PAGES):
            body = {
                "searchWord": watch.query,
                "keywordSource": "INPUT_KEYWORD",
                "actionDetailType": "NONE",
                "page": page,
                "size": JOONGNA_PAGE_SIZE,
                "sort": "RECENT_SORT",
                "filter": {},
            }
            try:
                response = await self.client.post(JOONGNA_SEARCH_API, json=body)
                response.raise_for_status()
                rows = self._rows(response.json())
            except Exception as exc:  # noqa: BLE001 - preserve earlier pages on partial outage
                self.last_search_complete = False
                self.last_search_errors.append(f"page {page}: {exc}")
                if not results:
                    raise
                break
            if not rows:
                break
            for row in rows:
                listing = self._parse_row(row)
                if listing is not None:
                    results[listing.external_id] = listing
        return list(results.values())

    async def close(self) -> None:
        await self.client.aclose()


class BunjangRuntimeProvider(Provider):
    """Bunjang JSON search API; location comes from the listing payload, not card text."""

    name = "bunjang"

    def __init__(self, timeout: int = 20):
        super().__init__()
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/152 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "ko-KR,ko;q=0.9",
                "Referer": "https://m.bunjang.co.kr/",
            },
        )

    @staticmethod
    def _parse_row(row: dict) -> Listing | None:
        item_id = row.get("pid")
        title = _first_value(row, "name", "title")
        if item_id is None or not title:
            return None
        price = legacy.coerce_price(_first_value(row, "price", "product_price"))
        image = _first_value(row, "product_image", "image")
        return Listing(
            "bunjang",
            str(item_id),
            str(title).strip(),
            price,
            f"https://m.bunjang.co.kr/products/{item_id}",
            location=_location_text(row),
            image_url=str(image) if image else None,
        )

    async def search(self, watch: Watch) -> list[Listing]:
        self.last_search_complete = True
        self.last_search_errors = []
        results: dict[str, Listing] = {}
        for page in range(BUNJANG_SEARCH_PAGES):
            params = {
                "q": watch.query,
                "order": "date",
                "page": str(page),
                "n": str(BUNJANG_PAGE_SIZE),
                "stat_device": "w",
                "req_ref": "search",
                "stat_category_required": "1",
                "version": "4",
            }
            try:
                response = await self.client.get(BUNJANG_SEARCH_API, params=params)
                response.raise_for_status()
                payload = response.json()
                rows = payload.get("list") or []
                if not isinstance(rows, list):
                    raise TypeError("Bunjang search payload shape changed: list missing")
            except Exception as exc:  # noqa: BLE001 - preserve earlier pages on partial outage
                self.last_search_complete = False
                self.last_search_errors.append(f"page {page}: {exc}")
                if not results:
                    raise
                break
            if not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                listing = self._parse_row(row)
                if listing is not None:
                    results[listing.external_id] = listing
        return list(results.values())

    async def close(self) -> None:
        await self.client.aclose()


def build_runtime_providers(timeout: int) -> dict[str, Provider]:
    return {
        "daangn": DaangnRuntimeProvider(timeout),
        "joongna": JoongnaRuntimeProvider(timeout),
        "bunjang": BunjangRuntimeProvider(timeout),
    }
