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
_DAANGN_SLUG_ID_RE = re.compile(r"-([a-z0-9]+)$", re.IGNORECASE)


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


def daangn_id_from_url(url: str) -> str:
    slug = url.rstrip("/").split("/")[-1]
    match = _DAANGN_SLUG_ID_RE.search(slug)
    return match.group(1) if match else slug


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


def _extract_daangn_articles(html: str) -> list[dict]:
    embedded = _extract_json_array(html, '"fleamarketArticles":')
    if embedded:
        return embedded

    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or payload.get("@type") != "ItemList":
            continue
        entries = payload.get("itemListElement")
        if not isinstance(entries, list):
            continue
        rows: list[dict] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            item = entry.get("item")
            if not isinstance(item, dict):
                continue
            offers = item.get("offers") if isinstance(item.get("offers"), dict) else {}
            image = item.get("image")
            if isinstance(image, list):
                image = image[0] if image else None
            rows.append(
                {
                    "href": item.get("url"),
                    "title": item.get("name"),
                    "price": offers.get("price"),
                    "thumbnail": image,
                    "status": "Ongoing",
                }
            )
        if rows:
            return rows
    return []


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
            headers={"User-Agent": "Mozilla/5.0 sale_bot/0.2 personal-monitor"},
        )

    async def search(self, watch: Watch) -> list[Listing]:
        url = f"https://web.joongna.com/search/{quote(watch.query)}"
        response = await self.client.get(url)
        response.raise_for_status()
        embedded = self._parse_embedded(response.text)
        if embedded:
            return embedded
        return self._parse_anchors(response.text)

    def _parse_embedded(self, html: str) -> list[Listing]:
        rows = _extract_json_array(html, '"items":')
        results: list[tuple[str, Listing]] = []
        for row in rows:
            seq = row.get("seq")
            title = row.get("title")
            if seq is None or not title:
                continue
            state = row.get("state")
            if isinstance(state, int) and state != 0:
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
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            },
        )
        self._region_cache: dict[str, dict] = {}

    async def _resolve_region(self, region: str) -> dict:
        if region in self._region_cache:
            return self._region_cache[region]
        response = await self.client.get(
            "https://www.daangn.com/kr/api/v1/regions/keyword",
            params={"keyword": region},
        )
        response.raise_for_status()
        payload = response.json()
        locations = payload.get("locations") or []
        if not locations:
            raise RuntimeError(f"Daangn region not found: {region}")
        exact = [
            item
            for item in locations
            if region in (item.get("name"), item.get("name1"), item.get("name2"), item.get("name3"))
        ]
        depth_three = [item for item in locations if item.get("depth") == 3]
        selected = (exact or depth_three or locations)[0]
        self._region_cache[region] = selected
        return selected

    async def _fetch_articles(self, watch: Watch, region_name: str | None) -> list[dict]:
        params: dict[str, str] = {"search": watch.query}
        if region_name:
            region = await self._resolve_region(region_name)
            region_id = region.get("dbId") or region.get("id")
            region_label = region.get("name")
            if not region_id or not region_label:
                raise RuntimeError(f"Daangn region has no usable slug: {region_name}")
            params["in"] = f"{region_label}-{region_id}"

        response = await self.client.get("https://www.daangn.com/kr/buy-sell/", params=params)
        response.raise_for_status()
        articles = _extract_daangn_articles(response.text)
        if articles:
            return articles

        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            return []
        all_page = payload.get("allPage") if isinstance(payload, dict) else None
        rows = all_page.get("fleamarketArticles") if isinstance(all_page, dict) else None
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    def _parse_articles(self, articles: list[dict]) -> list[Listing]:
        results: dict[str, Listing] = {}
        for article in articles:
            if str(article.get("status") or "Ongoing").casefold() == "closed":
                continue
            href = article.get("href") or article.get("webUrl")
            title = article.get("title")
            if not href or not title:
                continue
            full_url = urljoin("https://www.daangn.com", str(href))
            item_id = str(article.get("id") or daangn_id_from_url(full_url))
            region_data = article.get("region")
            location = article.get("locationName")
            if not location and isinstance(region_data, dict):
                location = region_data.get("name")
            image_url = article.get("thumbnail") or article.get("imageUrl") or article.get("thumbnailUrl")
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
        region_names: list[str | None] = watch.daangn_regions or [None]
        results: dict[str, Listing] = {}
        errors: list[str] = []
        successful_searches = 0

        for region_name in region_names:
            try:
                articles = await self._fetch_articles(watch, region_name)
            except Exception as exc:  # noqa: BLE001 - one region should not block the others
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
                no_results = ("검색 결과가 없습니다", "검색결과가 없습니다")
                if body and any(word in body for word in no_results):
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
                    || texts.find(t => /^\\d{4,}\\s*원$/.test(t))
                    || '';
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
