import json
import re
from abc import ABC, abstractmethod
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from .models import Listing, Watch

_PRICE_RE = re.compile(r"([0-9][0-9,]*)\s*원?")
_ID_RE = re.compile(r"/(?:products?|articles?)/(\d+)")


def parse_price(text: str | None) -> int | None:
    if not text:
        return None
    match = _PRICE_RE.search(text.replace(" ", ""))
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def stable_id_from_url(url: str) -> str:
    match = _ID_RE.search(url)
    return match.group(1) if match else url.rstrip("/").split("/")[-1]


class Provider(ABC):
    name: str

    @abstractmethod
    async def search(self, watch: Watch) -> list[Listing]: ...


class JoongnaProvider(Provider):
    name = "joongna"

    def __init__(self, timeout: int = 20):
        self.client = httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 sale_bot/0.1 personal-monitor"
        })

    async def search(self, watch: Watch) -> list[Listing]:
        url = f"https://web.joongna.com/search/{quote(watch.query)}"
        response = await self.client.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        results: dict[str, Listing] = {}
        for anchor in soup.select('a[href*="/product/"]'):
            href = anchor.get("href")
            if not href:
                continue
            full_url = urljoin("https://web.joongna.com", href)
            title = (anchor.get_text(" ", strip=True) or anchor.get("aria-label") or "").strip()
            if not title:
                image = anchor.find("img")
                title = (image.get("alt") if image else None) or "중고나라 매물"
            price = parse_price(anchor.get_text(" ", strip=True))
            item_id = stable_id_from_url(full_url)
            results[item_id] = Listing("joongna", item_id, title, price, full_url)
        return list(results.values())


class DaangnProvider(Provider):
    name = "daangn"

    def __init__(self, timeout: int = 20):
        self.client = httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 sale_bot/0.1 personal-monitor",
            "Accept": "text/html,application/xhtml+xml,application/json",
        })

    async def search(self, watch: Watch) -> list[Listing]:
        region = quote(watch.daangn_region or "대한민국")
        query = quote(watch.query)
        candidates = [
            f"https://www.daangn.com/kr/buy-sell/?in={region}&search={query}",
            f"https://www.daangn.com/search/{query}/",
        ]
        last_error: Exception | None = None
        for url in candidates:
            try:
                response = await self.client.get(url)
                response.raise_for_status()
                parsed = self._parse_html(response.text, response.url.copy_with(query=None).human_repr())
                if parsed:
                    return parsed
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        return []

    def _parse_html(self, html: str, base_url: str) -> list[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        results: dict[str, Listing] = {}
        for anchor in soup.select('a[href*="/articles/"], a[href*="/buy-sell/"]'):
            href = anchor.get("href")
            if not href:
                continue
            full_url = urljoin(base_url, href)
            text = anchor.get_text(" ", strip=True)
            title = text
            image = anchor.find("img")
            if image and image.get("alt"):
                title = image.get("alt")
            item_id = stable_id_from_url(full_url)
            if not item_id or item_id in results:
                continue
            results[item_id] = Listing(
                "daangn", item_id, title or "당근 매물", parse_price(text), full_url
            )
        if results:
            return list(results.values())

        # Remix/Next 계열 페이지의 JSON payload가 노출되는 경우를 위한 보수적 fallback.
        for script in soup.find_all("script"):
            body = script.string or ""
            if "article" not in body.lower() or "price" not in body.lower():
                continue
            try:
                data = json.loads(body)
            except Exception:
                continue
            self._walk_json(data, results)
        return list(results.values())

    def _walk_json(self, value, results: dict[str, Listing]) -> None:
        if isinstance(value, dict):
            title = value.get("title") or value.get("name")
            price = value.get("price")
            item_id = value.get("id") or value.get("articleId")
            url = value.get("url") or value.get("href")
            if title and item_id and url:
                try:
                    parsed_price = int(price) if price is not None else None
                except (TypeError, ValueError):
                    parsed_price = parse_price(str(price))
                results[str(item_id)] = Listing(
                    "daangn", str(item_id), str(title), parsed_price,
                    urljoin("https://www.daangn.com", str(url)),
                    location=str(value.get("regionName")) if value.get("regionName") else None,
                )
            for child in value.values():
                self._walk_json(child, results)
        elif isinstance(value, list):
            for child in value:
                self._walk_json(child, results)


class BunjangProvider(Provider):
    name = "bunjang"

    async def search(self, watch: Watch) -> list[Listing]:
        url = f"https://m.bunjang.co.kr/search/products?order=date&page=1&q={quote(watch.query)}"
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page(locale="ko-KR", viewport={"width": 430, "height": 932})
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)
            cards = await page.locator('a[href*="/products/"]').evaluate_all(
                """
                els => els.map(a => ({
                  href: a.href,
                  text: (a.innerText || '').trim(),
                  title: a.querySelector('img')?.alt || (a.innerText || '').trim(),
                  image: a.querySelector('img')?.src || null
                }))
                """
            )
            await browser.close()
        results: dict[str, Listing] = {}
        for card in cards:
            href = str(card.get("href") or "")
            match = re.search(r"/products/(\d+)", href)
            if not match:
                continue
            item_id = match.group(1)
            results[item_id] = Listing(
                "bunjang", item_id, str(card.get("title") or "번개장터 매물"),
                parse_price(str(card.get("text") or "")), href,
                image_url=card.get("image"),
            )
        return list(results.values())


def build_providers(timeout: int) -> dict[str, Provider]:
    return {
        "daangn": DaangnProvider(timeout),
        "joongna": JoongnaProvider(timeout),
        "bunjang": BunjangProvider(),
    }
