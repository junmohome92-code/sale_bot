import json
import re
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

CHEONGJU_ALL = "청주시 전체"
CHEONGJU_NEIGHBORHOODS = (
    "충청북도 청주시 상당구 낭성면",
    "충청북도 청주시 상당구 미원면",
    "충청북도 청주시 상당구 가덕면",
    "충청북도 청주시 상당구 남일면",
    "충청북도 청주시 상당구 문의면",
    "충청북도 청주시 상당구 중앙동",
    "충청북도 청주시 상당구 성안동",
    "충청북도 청주시 상당구 탑대성동",
    "충청북도 청주시 상당구 영운동",
    "충청북도 청주시 상당구 금천동",
    "충청북도 청주시 상당구 용담.명암.산성동",
    "충청북도 청주시 상당구 용암1동",
    "충청북도 청주시 상당구 용암2동",
    "충청북도 청주시 서원구 남이면",
    "충청북도 청주시 서원구 현도면",
    "충청북도 청주시 서원구 사직1동",
    "충청북도 청주시 서원구 사직2동",
    "충청북도 청주시 서원구 사창동",
    "충청북도 청주시 서원구 모충동",
    "충청북도 청주시 서원구 산남동",
    "충청북도 청주시 서원구 분평동",
    "충청북도 청주시 서원구 수곡1동",
    "충청북도 청주시 서원구 수곡2동",
    "충청북도 청주시 서원구 성화.개신.죽림동",
    "충청북도 청주시 흥덕구 오송읍",
    "충청북도 청주시 흥덕구 강내면",
    "충청북도 청주시 흥덕구 옥산면",
    "충청북도 청주시 흥덕구 운천.신봉동",
    "충청북도 청주시 흥덕구 복대1동",
    "충청북도 청주시 흥덕구 복대2동",
    "충청북도 청주시 흥덕구 가경동",
    "충청북도 청주시 흥덕구 봉명1동",
    "충청북도 청주시 흥덕구 봉명2.송정동",
    "충청북도 청주시 흥덕구 강서1동",
    "충청북도 청주시 흥덕구 강서2동",
    "충청북도 청주시 청원구 내수읍",
    "충청북도 청주시 청원구 오창읍",
    "충청북도 청주시 청원구 북이면",
    "충청북도 청주시 청원구 우암동",
    "충청북도 청주시 청원구 내덕1동",
    "충청북도 청주시 청원구 내덕2동",
    "충청북도 청주시 청원구 율량.사천동",
    "충청북도 청주시 청원구 오근장동",
)


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
    return re.sub(r"[\s>]+", "", text).casefold()


def _region_label(region: dict) -> str:
    return " > ".join(_region_parts(region))


def _region_leaf(region: str) -> str:
    tokens = [token for token in re.split(r"[\s>]+", region.strip()) if token]
    return tokens[-1] if tokens else region.strip()


def _select_region(requested: str, locations: list[dict]) -> dict:
    requested_norm = _norm_region(requested)
    exact_paths = [
        item for item in locations if _norm_region(" ".join(_region_parts(item))) == requested_norm
    ]
    if len(exact_paths) == 1:
        return exact_paths[0]

    requested_tokens = [token for token in re.split(r"[\s>]+", requested.strip()) if token]
    if len(requested_tokens) >= 2:
        contextual = [
            item
            for item in locations
            if all(
                _norm_region(token) in _norm_region(" ".join(_region_parts(item)))
                for token in requested_tokens
            )
        ]
        if len(contextual) == 1:
            return contextual[0]
        if len(contextual) > 1:
            labels = ", ".join(_region_label(item) for item in contextual[:5])
            raise RuntimeError(f"Daangn region ambiguous: {requested} -> {labels}")

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

    @abstractmethod
    async def search(self, watch: Watch) -> list[Listing]: ...

    async def close(self) -> None:
        return None


class JoongnaProvider(Provider):
    name = "joongna"

    def __init__(self, timeout: int = 20):
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 sale_bot/0.3 personal-monitor"},
        )

    async def search(self, watch: Watch) -> list[Listing]:
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
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 sale_bot/0.3 personal-monitor",
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            },
        )
        self._region_cache: dict[str, dict] = {}

    async def _resolve_region(self, region: str) -> dict:
        if region in self._region_cache:
            return self._region_cache[region]
        response = await self.client.get(
            "https://www.daangn.com/kr/api/v1/regions/keyword",
            params={"keyword": _region_leaf(region)},
        )
        response.raise_for_status()
        locations = response.json().get("locations") or []
        if not locations:
            raise RuntimeError(f"Daangn region not found: {region}")
        selected = _select_region(region, [item for item in locations if isinstance(item, dict)])
        self._region_cache[region] = selected
        return selected

    def region_targets(self, watch: Watch) -> list[str | None]:
        explicit = [region for region in watch.daangn_regions if region != CHEONGJU_ALL]
        targets: list[str | None] = list(explicit)
        if CHEONGJU_ALL in watch.daangn_regions:
            batch_count = max(
                1,
                min(int(watch.daangn_batch_count), len(CHEONGJU_NEIGHBORHOODS)),
            )
            batch_index = int(watch.daangn_batch_index) % batch_count
            city_batch = [
                region
                for index, region in enumerate(CHEONGJU_NEIGHBORHOODS)
                if index % batch_count == batch_index
            ]
            targets.extend(city_batch)
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
        results: dict[str, Listing] = {}
        errors: list[str] = []
        successful_searches = 0
        for region_name in self.region_targets(watch):
            try:
                articles = await self._fetch_articles(watch, region_name)
            except Exception as exc:  # noqa: BLE001 - one region should not block others
                errors.append(f"{region_name or '전체'}: {exc}")
                continue
            successful_searches += 1
            for listing in self._parse_articles(articles):
                results[listing.external_id] = listing
        if successful_searches == 0 and errors:
            raise RuntimeError("Daangn search failed: " + "; ".join(errors))
        if errors:
            print("[daangn] partial region failure: " + "; ".join(errors))
        return list(results.values())

    async def close(self) -> None:
        await self.client.aclose()


class BunjangProvider(Provider):
    name = "bunjang"

    def __init__(self, timeout: int = 20):
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
