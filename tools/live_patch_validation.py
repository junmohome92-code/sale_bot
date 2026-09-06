import asyncio
import json

import httpx

API = "https://search-api.joongna.com/v3/search/all"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Origin": "https://web.joongna.com",
    "Referer": "https://web.joongna.com/",
}


async def request(client, location_filter):
    body = {
        "searchWord": "닌텐도 스위치2",
        "keywordSource": "INPUT_KEYWORD",
        "actionDetailType": "NONE",
        "page": 0,
        "size": 20,
        "sort": "RECENT_SORT",
        "filter": {"locationFilter": location_filter},
    }
    return await client.post(API, json=body)


def detail(response):
    text = response.text.replace("\n", " ")
    try:
        payload = response.json()
        meta = payload.get("meta") or {}
        details = meta.get("detail") or []
        if details:
            return str(details[0].get("message") or details[0])[:1000]
        if response.status_code == 200:
            data = payload.get("data") or {}
            rows = data.get("items") or []
            locs = []
            for row in rows[:8]:
                if isinstance(row, dict):
                    locs.append(row.get("locationNames"))
            return f"total={data.get('totalSize')} locs={locs}"
    except Exception:
        pass
    return text[:1000]


async def main():
    # Put an intentionally wrong JSON type under likely field names. A real field should
    # make Jackson name that field in its path; unknown fields tend to be ignored and
    # fall through to the service's generic 500 for an empty LocationFilter.
    field_candidates = [
        "lat",
        "lng",
        "lon",
        "latitude",
        "longitude",
        "distance",
        "radius",
        "range",
        "rangeKm",
        "distanceKm",
        "locationId",
        "locationIds",
        "locationSeq",
        "locationSeqs",
        "regionId",
        "regionIds",
        "regionCode",
        "regionCodes",
        "code",
        "codes",
        "address",
        "addressName",
        "locationName",
        "locationNames",
        "name",
        "names",
        "city",
        "cityCode",
        "sido",
        "sigungu",
        "emd",
        "dong",
        "emdCode",
        "legalDongCode",
        "latitudeLongitude",
        "coordinates",
        "point",
        "center",
    ]
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=HEADERS) as client:
        for field in field_candidates:
            # Array/object mismatch is deliberate and makes valid scalar fields obvious.
            value = {field: {"__probe__": True}}
            try:
                response = await request(client, value)
                print(f"FIELD {field} STATUS {response.status_code} DETAIL {detail(response)}")
            except Exception as exc:
                print(f"FIELD {field} EXC {exc!r}")

        # Common coordinate object shapes, with Cheongju city-centre-ish coordinates.
        candidates = [
            {"latitude": 36.6424, "longitude": 127.4890, "distance": 30},
            {"latitude": 36.6424, "longitude": 127.4890, "radius": 30},
            {"lat": 36.6424, "lng": 127.4890, "distance": 30},
            {"lat": 36.6424, "lng": 127.4890, "radius": 30},
            {"lat": 36.6424, "lon": 127.4890, "radius": 30},
        ]
        for index, value in enumerate(candidates):
            try:
                response = await request(client, value)
                print(
                    "SHAPE",
                    index,
                    json.dumps(value, ensure_ascii=False),
                    "STATUS",
                    response.status_code,
                    "DETAIL",
                    detail(response),
                )
            except Exception as exc:
                print(f"SHAPE {index} EXC {exc!r}")


if __name__ == "__main__":
    asyncio.run(main())
