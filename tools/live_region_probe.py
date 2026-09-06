import asyncio
from urllib.parse import quote

from playwright.async_api import async_playwright

QUERY = "닌텐도 스위치2"


async def probe(name: str, url: str) -> None:
    print(f"\n===== {name} =====")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="ko-KR")

        def log_request(req):
            if req.resource_type in {"xhr", "fetch"}:
                print("REQ", req.method, req.url)

        page.on("request", log_request)
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            print("STATUS", resp.status if resp else None)
            await page.wait_for_timeout(4000)
            body = (await page.locator("body").inner_text()).replace("\r", "")
            print("BODY_HEAD")
            print("\n".join(body.splitlines()[:220]))

            for label in ("지역", "우리동네", "동네"):
                loc = page.get_by_text(label, exact=True)
                if await loc.count():
                    print("CLICK", label, "count", await loc.count())
                    try:
                        await loc.first.click(timeout=3000)
                        await page.wait_for_timeout(1500)
                        body2 = (await page.locator("body").inner_text()).replace("\r", "")
                        print("AFTER_CLICK", label)
                        print("\n".join(body2.splitlines()[:260]))
                    except Exception as exc:
                        print("CLICK_FAIL", label, repr(exc))
                    break
        except Exception as exc:
            print("PROBE_FAIL", repr(exc))
        finally:
            await browser.close()


async def main() -> None:
    encoded = quote(QUERY)
    await probe("joongna", f"https://web.joongna.com/search/{encoded}")
    await probe(
        "bunjang",
        f"https://m.bunjang.co.kr/search/products?order=date&page=1&q={encoded}",
    )


if __name__ == "__main__":
    asyncio.run(main())
