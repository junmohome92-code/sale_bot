import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import (
    Browser,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from .models import Listing, Watch

_PRICE_WITH_WON_RE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,})\s*원")
_COMMA_PRICE_RE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+)(?!\d)")
_ID_RE = re.compile(r"/(?:products?|articles?)/(\d+)")
_ALL_REGION_RE = re.compile(r"^(?P<scope>.+?)\s*전체$")
_ADMIN_SUFFIXES = (
    "특별자치시",
    "특별자치도",
    "특별시",
    "광역시",
    "자치구",
    "시",
    "군",
    "구",
    "읍",
    "면",
    "동",
)
_SCOPE_CACHE_TTL_SECONDS = 6 * 60 * 60
_SCOPE_DISCOVERY_CACHE: dict[str, tuple[float, list[dict]]] = {}


def parse_price(text: str | None) -> int | None:
    if not text:
        return None
    normalized = text.replace("\u00a0", " ")
    match = _PRICE_WITH_WON_RE.search(normalized) or _COMMA_PRICE_RE.search(normalized)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def coerce_price(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return parse_price(text)


def stable_id_from_url(url: str) -> str:
    match = _ID_RE.search(url)
    return match.group(1) if match else url.rstrip("/").split("/")[-1]


def _balanced_json(text: str, start: int, opener: str) -> str | None:
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _extract_json_array(html: str, marker: str) -> list[dict]:
    for candidate in (marker, marker.replace('"', '\\"')):
        marker_index = html.find(candidate)
        if marker_index < 0:
            continue
        tail = html[marker_index + len(candidate) :]
        for value in (tail, tail.replace('\\"', '"').replace("\\\\", "\\")):
            start = value.find("[")
            if start < 0:
                continue
            payload = _balanced_json(value, start, "[")
            if not payload:
                continue
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
    return []


def _region_parts(region: dict) -> list[str]:
    parts: list[str] = []
    for key in ("name1", "name2", "name3", "name"):
        value = region.get(key)
        if value and str(value) not in parts:
            parts.append(str(value))
    return parts


def _norm_region(text: str) -> str:
    return re.sub(r"[\s>._·-]+", "", text).casefold()


def _region_label(region: dict) -> str:
    return " > ".join(_region_parts(region))


def _region_leaf(region: str) -> str:
    tokens = [token for token in re.split(r"[\s>]+", region.strip()) if token]
    return tokens[-1] if tokens else region.strip()


def _geo_key(text: str) -> str:
    value = _norm_region(text)
    for suffix in _ADMIN_SUFFIXES:
        suffix_key = _norm_region(suffix)
        if value.endswith(suffix_key) and len(value) > len(suffix_key):
            return value[: -len(suffix_key)]
    return value


def _geo_tokens(text: str) -> list[str]:
    tokens = [token for token in re.split(r"[\s>]+", text.strip()) if token]
    return [key for key in (_geo_key(token) for token in tokens) if key]


def _candidate_geo_keys(region: dict) -> set[str]:
    keys: set[str] = set()
    for part in _region_parts(region):
        for token in re.split(r"[\s>]+", part):
            if token:
                keys.add(_geo_key(token))
    return keys


def _scope_matches(scope: str, region: dict) -> bool:
    requested = _geo_tokens(scope)
    if not requested:
        return False
    candidate = _candidate_geo_keys(region)
    return all(token in candidate for token in requested)


def daangn_all_scope(region: str) -> str | None:
    match = _ALL_REGION_RE.match(region.strip())
    if not match:
        return None
    scope = match.group("scope").strip()
    return scope or None


def has_daangn_all_scope(regions: list[str]) -> bool:
    return any(daangn_all_scope(region) is not None for region in regions)


def daangn_scope_key(regions: list[str]) -> str:
    scopes = sorted(
        _norm_region(scope)
        for region in regions
        if (scope := daangn_all_scope(region)) is not None
    )
    payload = "|".join(scopes)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _scope_query_terms(scope: str) -> list[str]:
    terms: list[str] = []
    raw_tokens = [token for token in re.split(r"[\s>]+", scope.strip()) if token]
    for candidate in [scope.strip(), *reversed(raw_tokens)]:
        if candidate and candidate not in terms:
            terms.append(candidate)
        key = _geo_key(candidate)
        if key and key not in terms:
            terms.append(key)
    return terms


def _select_region(requested: str, locations: list[dict]) -> dict:
    requested_norm = _norm_region(requested)
    exact_paths = [
        item for item in locations if _norm_region(" ".join(_region_parts(item))) == requested_norm
    ]
    if len(exact_paths) == 1:
        return exact_paths[0]

    requested_tokens = [token for token in re.split(r"[\s>]+", requested.strip()) if token]
    if len(requested_tokens) >= 2:
        contextual = [item for item in locations if _scope_matches(requested, item)]
        leaf_norm = _norm_region(_region_leaf(requested))
        contextual = [
            item
            for item in contextual
            if leaf_norm
            in {
                _norm_region(str(item.get("name") or "")),
                _norm_region(str(item.get("name3") or "")),
            }
        ]
        if len(contextual) == 1:
            return contextual[0]
        if len(contextual) > 1:
            labels = ", ".join(_region_label(item) for item in contextual[:5])
            raise RuntimeError(f"Daangn region ambiguous: {requested} -> {labels}")
        raise RuntimeError(f"Daangn region not found in requested context: {requested}")

    leaf_norm = _norm_region(_region_leaf(requested))
    leaf_exact = [
        item
        for item in locations
        if leaf_norm in {_norm_region(str(item.get(key) or "")) for key in ("name", "name3")}
    ]
    if len(leaf_exact) == 1:
        return leaf_exact[0]
    if len(leaf_exact) > 1:
        labels = ", ".join(_region_label(item) for item in leaf_exact[:5])
        raise RuntimeError(f"Daangn region ambiguous: {requested} -> {labels}")

    if len(locations) == 1:
        return locations[0]
    labels = ", ".join(_region_label(item) for item in locations[:5])
    raise RuntimeError(f"Daangn region not uniquely resolved: {requested} -> {labels}")


class Provider(ABC):
    name: str

    def __init__(self) -> None:
        self.last_search_complete = True
        self.last_search_errors: list[str] = []

    @abstractmethod
    async def search(self, watch: Watch) -> list[Listing]: ...

    async def close(self) -> None:
        return None


class JoongnaProvider(Provider):
    name = "joongna"

    def __init__(self, timeout: int = 20):
        super().__init__()
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 sale_bot/0.4 personal-monitor"},
        )

    async def search(self, watch: Watch) -> list[Listing]:
        self.last_search_complete = True
        self.last_search_errors = []
        url = f"https://web.joongna.com/search/{quote(watch.query)}"
        response = await self.client.get(url)
        response.raise_for_status()
        embedded = self._parse_embedded(response.text)
        return embedded if embedded else self._parse_anchors(response.text)

    def _parse_embedded(self, html: str) -> list[Listing]:
        rows = _extract_json_array(html, '"items":')
        results: list[tuple[str, Listing]] = []
        for row in rows:
            seq = row.get("seq")
            title = row.get("title")
            if seq is None or not title or (
                isinstance(row.get("state"), int) and row.get("state") != 0
            ):
                continue
            locations = row.get("locationNames")
            location = row.get("mainLocationName")
            if not location and isinstance(locations, list) and locations:
                location = locations[0]
            listing = Listing(
                "joongna",
                str(seq),
                str(title),
                coerce_price(row.get("price")),
                f"https://web.joongna.com/product/{seq}",
                location=str(location) if location else None,
                image_url=str(row.get("url")) if row.get("url") else None,
            )
            results.append((str(row.get("sortDate") or ""), listing))
        results.sort(key=lambda item: item[0], reverse=True)
        return [listing for _, listing in results]

    def _parse_anchors(self, html: str) -> list[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        results: dict[str, Listing] = {}
        for anchor in soup.select('a[href*="/product/"]'):
            href = anchor.get("href")
            if not href:
                continue
            full_url = urljoin("https://web.joongna.com", href)
            text = anchor.get_text(" ", strip=True)
            image = anchor.find("img")
            title = (image.get("alt") if image else None) or text or "중고나라 매물"
            item_id = stable_id_from_url(full_url)
            results[item_id] = Listing(
                "joongna",
                item_id,
                str(title).strip(),
                parse_price(text),
                full_url,
                image_url=(image.get("src") if image else None),
            )
        return list(results.values())

    async def close(self) -> None:
        await self.client.aclose()


class DaangnProvider(Provider):
    name = "daangn"

    def __init__(self, timeout: int = 20):
        super().__init__()
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 sale_bot/0.4 personal-monitor",
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            },
        )
        self._region_cache: dict[str, dict] = {}
        self._candidate_cache: dict[str, list[dict]] = {}
        self.last_scope_expansions: dict[str, list[str]] = {}
        self.last_search_target_count = 0

    async def _region_candidates(self, keyword: str) -> list[dict]:
        keyword = keyword.strip()
        if keyword in self._candidate_cache:
            return self._candidate_cache[keyword]
        response = await self.client.get(
            "https://www.daangn.com/kr/api/v1/regions/keyword",
            params={"keyword": keyword},
        )
        response.raise_for_status()
        locations = [
            item for item in (response.json().get("locations") or []) if isinstance(item, dict)
        ]
        self._candidate_cache[keyword] = locations
        return locations

    async def _resolve_region(self, region: str) -> dict:
        if region in self._region_cache:
            return self._region_cache[region]
        locations = await self._region_candidates(_region_leaf(region))
        if not locations:
            raise RuntimeError(f"Daangn region not found: {region}")
        selected = _select_region(region, locations)
        self._region_cache[region] = selected
        return selected

    async def _discover_scope_regions(self, scope: str) -> list[dict]:
        cache_key = _norm_region(scope)
        cached = _SCOPE_DISCOVERY_CACHE.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < _SCOPE_CACHE_TTL_SECONDS:
            regions = [dict(item) for item in cached[1]]
            for item in regions:
                self._region_cache[_region_label(item).replace(" > ", " ")] = item
            return regions

        seeds: dict[tuple[object, object, object], dict] = {}
        for term in _scope_query_terms(scope):
            for item in await self._region_candidates(term):
                if int(item.get("depth") or 0) not in {2, 3}:
                    continue
                if not _scope_matches(scope, item):
                    continue
                key = (
                    item.get("name1Id"),
                    item.get("name2Id"),
                    item.get("name3Id") or item.get("id"),
                )
                seeds[key] = item

        if not seeds:
            raise RuntimeError(f"Daangn broad region not found: {scope} 전체")

        if len(_geo_tokens(scope)) == 1:
            parents = {
                (_geo_key(str(item.get("name1") or "")), _geo_key(str(item.get("name2") or "")))
                for item in seeds.values()
            }
            provinces = {parent[0] for parent in parents}
            if len(provinces) > 1:
                labels = ", ".join(_region_label(item) for item in list(seeds.values())[:5])
                raise RuntimeError(f"Daangn broad region ambiguous: {scope} 전체 -> {labels}")

        group_seeds: dict[object, dict] = {}
        direct_depth3: dict[object, dict] = {}
        for item in seeds.values():
            if int(item.get("depth") or 0) == 3:
                direct_depth3[item.get("name3Id") or item.get("id")] = item
            group_key = item.get("name2Id") or item.get("name2")
            if group_key is not None:
                group_seeds[group_key] = item

        discovered: dict[object, dict] = dict(direct_depth3)
        for group_key, seed in group_seeds.items():
            name2 = str(seed.get("name2") or seed.get("name") or "").strip()
            terms = [name2, _region_leaf(name2), _geo_key(_region_leaf(name2))]
            for term in dict.fromkeys(term for term in terms if term):
                for item in await self._region_candidates(term):
                    if int(item.get("depth") or 0) != 3:
                        continue
                    item_group = item.get("name2Id") or item.get("name2")
                    if item_group != group_key or not _scope_matches(scope, item):
                        continue
                    discovered[item.get("name3Id") or item.get("id")] = item

        if not discovered:
            raise RuntimeError(f"Daangn broad region has no searchable neighborhoods: {scope} 전체")

        regions = sorted(
            discovered.values(),
            key=lambda item: (
                str(item.get("name1") or ""),
                str(item.get("name2") or ""),
                str(item.get("name3") or item.get("name") or ""),
            ),
        )
        for item in regions:
            self._region_cache[_region_label(item).replace(" > ", " ")] = item
        _SCOPE_DISCOVERY_CACHE[cache_key] = (now, [dict(item) for item in regions])
        return regions

    async def region_targets(self, watch: Watch) -> list[str | None]:
        explicit: list[str] = []
        broad_specs: list[tuple[str, str]] = []
        for region in watch.daangn_regions:
            scope = daangn_all_scope(region)
            if scope is None:
                explicit.append(region)
            else:
                broad_specs.append((region, scope))

        targets: list[str | None] = list(explicit)
        self.last_scope_expansions = {}
        for original, scope in broad_specs:
            discovered = await self._discover_scope_regions(scope)
            labels = [_region_label(item).replace(" > ", " ") for item in discovered]
            self.last_scope_expansions[original] = labels
            batch_count = max(1, min(int(watch.daangn_batch_count), len(labels)))
            batch_index = int(watch.daangn_batch_index) % batch_count
            targets.extend(
                label for index, label in enumerate(labels) if index % batch_count == batch_index
            )
        if not targets:
            return [None]
        return list(dict.fromkeys(targets))

    async def all_region_targets(self, watch: Watch) -> list[str | None]:
        targets: list[str | None] = []
        self.last_scope_expansions = {}
        for region in watch.daangn_regions:
            scope = daangn_all_scope(region)
            if scope is None:
                targets.append(region)
                continue
            discovered = await self._discover_scope_regions(scope)
            labels = [_region_label(item).replace(" > ", " ") for item in discovered]
            self.last_scope_expansions[region] = labels
            targets.extend(labels)
        if not targets:
            return [None]
        return list(dict.fromkeys(targets))

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
        response = await self.client.get(f"https://www.daangn.com{path}", params=params)
        response.raise_for_status()
        payload = response.json()
        all_page = payload.get("allPage")
        if not isinstance(all_page, dict):
            raise RuntimeError("Daangn search payload shape changed: allPage missing")
        articles = all_page.get("fleamarketArticles")
        if not isinstance(articles, list):
            raise RuntimeError("Daangn search payload shape changed: fleamarketArticles missing")
        return [article for article in articles if isinstance(article, dict)]

    def _parse_articles(self, articles: list[dict]) -> list[Listing]:
        results: dict[str, Listing] = {}
        for article in articles:
            href = article.get("href") or article.get("webUrl")
            title = article.get("title")
            if not href or not title:
                continue
            full_url = urljoin("https://www.daangn.com", str(href))
            item_id = stable_id_from_url(full_url)
            region_data = article.get("region")
            location = region_data.get("name") if isinstance(region_data, dict) else None
            image_url = article.get("imageUrl") or article.get("thumbnailUrl")
            results[item_id] = Listing(
                "daangn",
                item_id,
                str(title),
                coerce_price(article.get("price")),
                full_url,
                location=str(location) if location else None,
                image_url=str(image_url) if image_url else None,
            )
        return list(results.values())

    async def search(self, watch: Watch) -> list[Listing]:
        self.last_search_complete = True
        self.last_search_errors = []
        results: dict[str, Listing] = {}
        targets = await self.region_targets(watch)
        self.last_search_target_count = len(targets)
        successful_searches = 0
        for region_name in targets:
            try:
                articles = await self._fetch_articles(watch, region_name)
            except Exception as exc:  # noqa: BLE001 - one region should not block others
                self.last_search_errors.append(f"{region_name or '전체'}: {exc}")
                continue
            successful_searches += 1
            for listing in self._parse_articles(articles):
                results[listing.external_id] = listing
        self.last_search_complete = not self.last_search_errors
        if successful_searches == 0 and self.last_search_errors:
            raise RuntimeError("Daangn search failed: " + "; ".join(self.last_search_errors))
        if self.last_search_errors:
            print("[daangn] partial region failure: " + "; ".join(self.last_search_errors))
        return list(results.values())

    async def close(self) -> None:
        await self.client.aclose()


class BunjangProvider(Provider):
    name = "bunjang"

    def __init__(self, timeout: int = 20):
        super().__init__()
        self.timeout_ms = timeout * 1000
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def _ensure_browser(self) -> Browser:
        if self._browser is not None:
            return self._browser
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        return self._browser

    async def search(self, watch: Watch) -> list[Listing]:
        self.last_search_complete = True
        self.last_search_errors = []
        url = f"https://m.bunjang.co.kr/search/products?order=date&page=1&q={quote(watch.query)}"
        browser = await self._ensure_browser()
        page = await browser.new_page(locale="ko-KR", viewport={"width": 430, "height": 932})
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            try:
                await page.wait_for_selector(
                    'a[href*="/products/"]', timeout=min(7000, self.timeout_ms)
                )
            except PlaywrightTimeoutError:
                body = (await page.locator("body").inner_text()).strip()
                if body and any(
                    word in body for word in ("검색 결과가 없습니다", "검색결과가 없습니다")
                ):
                    return []
                raise RuntimeError(
                    "Bunjang search cards did not load; page structure or access may have changed"
                )
            cards = await page.locator('a[href*="/products/"]').evaluate_all(
                """
                els => els.map(a => {
                  const texts = [...a.querySelectorAll('div,span,p')]
                    .map(n => (n.textContent || '').trim())
                    .filter(Boolean);
                  const priceText = texts.find(t => /^\\d{1,3}(,\\d{3})+\\s*원?$/.test(t))
                    || texts.find(t => /^\\d{4,}\\s*원$/.test(t)) || '';
                  return {
                    href: a.href,
                    text: (a.innerText || '').trim(),
                    title: a.querySelector('img')?.alt || texts[0] || '',
                    priceText,
                    image: a.querySelector('img')?.src || null
                  };
                })
                """
            )
        finally:
            await page.close()
        results: dict[str, Listing] = {}
        for card in cards:
            href = str(card.get("href") or "")
            match = re.search(r"/products/(\d+)", href)
            if not match:
                continue
            item_id = match.group(1)
            price = parse_price(str(card.get("priceText") or ""))
            if price is None:
                price = parse_price(str(card.get("text") or ""))
            results[item_id] = Listing(
                "bunjang",
                item_id,
                str(card.get("title") or "번개장터 매물").strip(),
                price,
                href,
                image_url=str(card.get("image")) if card.get("image") else None,
            )
        return list(results.values())

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None


def build_providers(timeout: int) -> dict[str, Provider]:
    return {
        "daangn": DaangnProvider(timeout),
        "joongna": JoongnaProvider(timeout),
        "bunjang": BunjangProvider(timeout),
    }
