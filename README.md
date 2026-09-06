# sale_bot

중고나라 · 당근 · 번개장터의 검색 결과를 주기적으로 확인하고, 조건에 맞는 중고매물을 Telegram으로 알려주는 개인용 감시 봇입니다.

Ubuntu 홈서버에서는 Docker로 상시 실행하고, 감시 슬롯 추가/수정/삭제는 **Telegram `/menu` 버튼 UI**에서 관리하는 것을 기본 사용법으로 합니다. Discord는 선택적인 알림 Webhook만 지원합니다.

> 읽기 전용 검색/모니터링만 대상으로 합니다. 로그인·CAPTCHA 우회, 자동 채팅, 자동 구매는 구현하지 않습니다.

## 현재 핵심 동작

- 감시 슬롯 최대 **20개**
- 슬롯별 최소/최대 가격 설정
- 슬롯별 `N원 이하 무시` 가격 설정
- 슬롯별 `삽니다` / `팝니다` 게시글 제외 설정
- 사용자 지정 제외 키워드 지원
- 당근은 입력한 시/구/동 범위를 적용
- 여러 지역 동시 등록 가능
- 중고나라/번개장터는 설정 지역의 **시 단위**를 적용
- 최초 등록 직후 즉시 첫 검색
- 첫 검색에서 조건에 맞는 기존 매물을 **마켓별 최대 3개**까지 링크와 함께 전송
- 첫 검색 이후 새 조건충족 매물 알림
- 같은 매물의 실제 가격이 내려갈 때마다 다시 알림
- 같은 가격 반복 / 가격 상승은 알림하지 않음
- 슬롯별 추적 상태를 `watch_id` 기준으로 독립 저장
- 슬롯 삭제 시 해당 슬롯의 가격/알림/검색 상태까지 완전 삭제

## Telegram 등록 흐름

`/menu` → `➕ 감시 추가`를 누르면 다음 순서로 등록합니다.

```text
상품/키워드
→ 최대가격 또는 가격범위
→ 무시가격
→ 거래유형 선택
→ 지역
→ 최종 확인
→ 등록
```

거래유형 선택 화면의 기본값은 다음과 같습니다.

```text
✅ 삽니다 제외
⬜ 팝니다 허용
```

등록 중 두 값을 각각 토글할 수 있으며, 최종 확인 화면에 선택값이 표시됩니다. 등록 후에도 감시 슬롯 상세 화면에서 다시 변경할 수 있습니다.

감시 슬롯 상세에서는 다음 항목을 관리할 수 있습니다.

```text
💰 가격 변경
🚫 무시가격
✅/⬜ 삽니다 제외/허용
✅/⬜ 팝니다 제외/허용
📍 지역 변경
⏸ 일시정지 / ▶️ 재개
🗑 완전 삭제
```

주요 명령어:

```text
/menu
/add
/list
/status
/help
```

`/도움말`, `/?`, `도움말`, `메뉴`도 인식합니다.

## 거래유형 필터

`삽니다 제외`가 켜져 있으면 제목에서 명확한 구매 의도 표현을 감지해 제외합니다.

예:

```text
삽니다
구합니다
구해요
구함
구매합니다 / 구매 원합니다
매입합니다 / 매입해요
```

`팝니다 제외`가 켜져 있으면 다음과 같은 판매 의도 표현을 제외합니다.

```text
팝니다
팔아요
판매합니다 / 판매해요 / 판매중
처분합니다 / 처분해요
```

단순히 `구매`라는 단어만 있다고 구매글로 판정하지 않습니다. 예를 들어 `구매 후 미사용, 팝니다` 같은 판매글의 오탐을 줄이기 위한 처리입니다.

## 가격 조건

예를 들어:

```text
최대가격: 700,000원
무시가격: 50,000원 이하
```

이면 `50,001원 ~ 700,000원` 범위의 매물이 조건에 들어옵니다.

`무시가격 = 0`이면 기능을 사용하지 않습니다.

가격 알림 예:

```text
1,200,000원 → 알림 없음
  990,000원 → 🔔 새 조건충족
  990,000원 → 알림 없음
  800,000원 → 🔔 가격 하락
  900,000원 → 알림 없음
  850,000원 → 🔔 가격 하락
```

가격이 한 번 올랐다가 다시 내려간 경우에도 **직전 관측가보다 실제로 내려갔다면** 알림 대상입니다.

## 첫 검색 결과

새 슬롯을 등록하거나 필터 조건을 바꿔 추적 기준선이 초기화되면 첫 검색을 다시 수행합니다.

첫 검색에서는 현재 조건에 맞는 기존 매물을 단순히 숨기지 않고 사용자에게 보여줍니다.

- Provider별 최대 3개
- 3개 마켓 전체 최대 9개
- 가격이 있는 매물은 저가순 우선
- 이후 같은 기존 매물을 새 매물처럼 반복 알림하지 않도록 기준선을 저장

## 지역 정책

### 당근

Telegram에서 입력한 지역을 저장 전에 실제 지역 데이터로 검증합니다.

예:

```text
청주시
청주시 청원구
청주시 청원구 오창읍
청주시, 세종시
청주시 청원구, 세종시
```

예시 동작:

- `청주시` → `청주시 전체`
- `청주시 청원구` → 해당 구 전체
- 동/읍/면 입력 → 해당 세부 지역
- 없는 지역 → 등록 거부
- 애매한 지역명 → 임의 선택하지 않고 더 구체적인 입력 요구

넓은 지역은 실제 검색 가능한 하위 지역들로 확장해 순차 검색합니다.

### 중고나라 / 번개장터

당근에 설정한 여러 지역에서 **도시 단위**를 파생합니다.

예:

```text
당근: 청주시 청원구, 세종시
중고나라/번개장터: 청주시, 세종시
```

중고나라와 번개장터는 검색 결과의 구조화된 위치 데이터를 최종 지역 판정에 사용합니다. 지역 제한이 설정된 상태에서 위치 정보를 확인할 수 없는 매물은 지역 일치로 처리하지 않습니다.

## 검색 방식

별도 유료 검색 API Key는 사용하지 않습니다.

- 당근: 현재 웹 서비스의 검색/지역 요청 + 요청 간격 조절/backoff
- 중고나라: `search-api.joongna.com` JSON 검색 API, 도시명+키워드 검색 후 구조화된 위치 검증
- 번개장터: `api.bunjang.co.kr` JSON 검색 API, 구조화된 `location` 값으로 도시 검증

현재 번개장터 런타임 검색은 Playwright 카드 텍스트 추정 방식이 아닙니다.

## 검색주기

기본 검색 목표주기는 **15분**입니다.

```yaml
poll_interval_seconds: 900
```

Telegram `⚙️ 설정`에서 다음 값을 선택할 수 있습니다.

```text
5분 / 10분 / 15분 / 30분
```

각 Provider는 독립 루프로 동작합니다. 당근처럼 넓은 지역 × 많은 키워드 조합이 설정 주기보다 오래 걸리면, 완료 후 불필요하게 추가 대기하지 않고 다음 순환을 이어갑니다.

당근 요청은 기본적으로 약 1.2초 이상의 간격을 두고 순차 실행하며 403/429/5xx 응답 시 자동 backoff 합니다.

## 설정의 기준

운영 중 감시 설정의 Source of Truth는 **SQLite DB**입니다.

- `.env`: Telegram Token / Chat ID / 선택적 Discord Webhook
- `config.yaml`: 기본 검색주기, timeout, 새 DB의 선택적 최초 seed
- SQLite: 실제 슬롯, 가격, 무시가격, 거래유형 필터, 지역, 제외어, ON/OFF, 추적/알림 상태

기본 설정:

```yaml
poll_interval_seconds: 900
request_timeout_seconds: 20
watches: []
```

`config.yaml`의 `watches`는 새 DB에서 한 번만 seed 용도로 사용하고, 이후 운영 설정은 Telegram에서 관리하는 것을 권장합니다.

## SQLite / schema

현재 런타임 schema version은 **4**입니다.

주요 테이블:

- `managed_watches`: 감시 슬롯 설정
- `runtime_state`: schema version 및 런타임 상태
- `watch_listing_state`: 슬롯별 매물 추적 상태
- `watch_price_history`: 가격 이력
- `pending_alerts`: 미전송 알림
- `watch_scan_state`: Provider별 첫 검색 완료 여부
- `provider_status`: 최근 Provider 실행 상태

기존 DB에 거래유형 컬럼이 없으면 자동으로 추가합니다.

```text
exclude_buying_posts
exclude_selling_posts
```

기본값은:

```text
삽니다 제외 = ON
팝니다 제외 = OFF
```

거래유형/가격조건 등 검색 조건을 변경하면 해당 슬롯의 추적 기준선을 다시 잡습니다.

## Ubuntu Docker 설치

예: 별도 데이터 디스크가 `/data`에 마운트되어 있다면 소스는 다음처럼 둘 수 있습니다.

```bash
cd /data
git clone https://github.com/junmohome92-code/sale_bot.git
cd sale_bot

cp config.example.yaml config.yaml
cp .env.example .env
# .env에 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 입력

docker compose up -d --build
docker compose ps
```

로그 확인:

```bash
docker compose logs --tail=100 sale-bot
docker compose logs -f sale-bot
```

`docker compose logs -f`에서 `Ctrl+C`를 눌러도 `-d`로 실행한 컨테이너는 계속 동작합니다.

`restart: unless-stopped`가 적용되어 Docker 서비스가 부팅 시 시작되면 컨테이너도 다시 올라옵니다.

### Docker 데이터 위치 주의

현재 `compose.yaml`은 SQLite `/data/sale_bot.sqlite3`를 **Docker named volume `sale_bot_data`**에 저장합니다.

따라서 저장소를 `/data/sale_bot`에 clone했다고 해서 SQLite 파일도 반드시 호스트의 `/data` 물리 디스크에 저장되는 것은 아닙니다. named volume의 실제 호스트 위치는 Docker의 `data-root` 설정을 따릅니다.

즉:

```text
/data/sale_bot        = Git 소스 위치
sale_bot_data volume  = SQLite 런타임 데이터 위치
```

둘을 같은 물리 디스크에 두고 싶다면 compose의 데이터 볼륨을 host bind mount로 변경해야 합니다.

수동 1회 검색:

```bash
docker compose run --rm sale-bot python -m sale_bot.main --once
```

## Windows 테스트

Windows 테스트는 저장소의 다음 런처를 사용합니다.

```text
sale_bot - sale test win\SALE_TEST.bat
```

Windows 폴더는 런처/진단 도구를 제공하고 실제 Python 코드는 루트 `src/`를 사용합니다. Ubuntu와 Windows에서 별도 Python 소스 복사본을 유지하지 않습니다.

## 알림 환경변수

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# 선택
DISCORD_WEBHOOK_URL=
```

Discord는 알림 전용이며 설정 관리는 Telegram으로 통일합니다.
