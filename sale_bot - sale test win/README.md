# sale_bot

중고나라 · 당근 · 번개장터의 공개 검색 결과를 주기적으로 확인하고, 설정한 **상품이 지정 가격 이하로 올라오면 매물당 최초 1회만** Telegram / Discord / KakaoTalk(선택)으로 알리는 개인용 가격 추적 봇입니다.

Ubuntu 홈서버에는 **Docker와 Docker Compose만 있으면 됩니다.** Python, Playwright, Chromium 등 실행 의존성은 Docker 이미지 안에 설치됩니다.

## 주요 기능

- 감시 키워드 최대 **3슬롯**
- 상품별 **최대 알림 가격** 설정
- 제외 키워드(예: `삽니다`, `구매`, `매입`) 추가/삭제
- Telegram에서 감시항목 추가/수정/삭제/일시정지
- Discord Bot을 설정한 경우 동일한 관리 명령 지원
- 같은 watch + 같은 사이트 + 같은 매물 ID는 **최초 1회만 알림**
- 첫 검색에서 가격이 너무 높아 무시된 매물이 나중에 가격 상한 이하로 내려오면 그때 최초 1회 알림
- 사이트별 독립 provider
- SQLite 매물/가격 이력/감시 설정/중복 알림 기록
- Telegram Bot API / Discord Webhook 알림
- KakaoTalk `나에게 보내기` 선택 지원
- Docker 상시 실행 및 서버 재부팅 후 자동 재시작
- 첫 실행 시 기존 조건 충족 매물을 조용히 기준선으로 저장하는 bootstrap 모드

> 이 프로젝트는 읽기 전용 검색/모니터링만 대상으로 합니다. 로그인·CAPTCHA·봇 차단 우회, 자동 채팅, 자동 구매는 구현하지 않습니다. 각 사이트의 이용약관과 접근 정책을 준수하고 과도한 요청을 피하세요.

## Provider 전략

- **Daangn**: 공개 검색 데이터 표면을 읽기 전용으로 사용하며 지역을 설정할 수 있습니다.
- **Joongna**: 공개 검색 페이지의 구조화된 검색 데이터와 상품 링크를 사용합니다.
- **Bunjang**: 공개 검색 페이지를 컨테이너 내부 Playwright/Chromium으로 읽습니다.

사이트 구조가 변경되면 해당 provider만 수정하면 되도록 서로 분리되어 있습니다.

## Ubuntu 홈서버 배포

```bash
# 1. 저장소를 받은 뒤 프로젝트 폴더로 이동
cd sale_bot

# 2. 개인 설정 파일 생성
cp config.example.yaml config.yaml
cp .env.example .env

# 3. config.yaml에서 최초 seed 감시항목과 polling 설정 확인
# 4. .env에서 Telegram 또는 Discord 자격정보 입력

# 5. 이미지 빌드 + 백그라운드 실행
docker compose up -d --build

# 6. 상태 확인
docker compose ps

# 7. 로그 확인
docker compose logs -f --tail=100 sale-bot
```

`restart: unless-stopped`가 적용되어 있으므로 Docker가 부팅 시 시작되는 서버에서는 재부팅 후 컨테이너도 자동으로 다시 올라옵니다.

## 감시 설정 구조

`config.yaml`의 `watches`는 **DB가 처음 만들어질 때 한 번만 seed**됩니다. 그 이후 실제 감시항목의 Source of Truth는 Docker volume 안의 SQLite DB입니다.

따라서 Telegram/Discord에서 항목을 삭제하거나 수정해도 다음 polling 주기에 YAML이 다시 덮어쓰지 않습니다.

최대 감시항목은 3개입니다.

```yaml
poll_interval_seconds: 300
alert_on_first_seen: true
alert_on_price_increase: false
bootstrap_silently: true
request_timeout_seconds: 20

watches:
  - name: "RX 9070 XT"
    query: "9070 xt"
    max_price: 900000
    exclude_keywords: ["삽니다", "구매", "매입"]
    providers: [daangn, joongna, bunjang]
    daangn_region: "청주시"
```

## Telegram / Discord 관리 명령

```text
/add 상품명 | 최대가격 | 당근지역(선택)
/list
/price ID 최대가격
/region ID 지역명
/exclude ID add 단어
/exclude ID del 단어
/pause ID
/resume ID
/delete ID
/help
```

예:

```text
/add 9070 XT | 900000 | 청주시
/exclude 1 add 삽니다
/exclude 1 add 구합니다
/price 1 850000
/list
```

동작 예시는 다음과 같습니다.

```text
9070 XT / 850,000원 / 새 매물  -> 알림 1회
같은 매물을 다음 검색에서 재발견 -> 알림 없음
같은 매물 가격이 다시 변함       -> 이미 알림했다면 추가 알림 없음
기존 950,000원 매물이 890,000원으로 인하 -> 조건을 처음 만족하므로 알림 1회
```

## 첫 실행 동작

기본값 `bootstrap_silently: true`에서는 처음 실행할 때 이미 존재하는 **조건 충족 매물**을 중복방지 DB에 기준선으로 기록하지만 알림은 보내지 않습니다. 이후 새로 조건을 만족하는 매물부터 알림이 갑니다.

처음부터 현재 조건 충족 검색 결과도 모두 알림 받고 싶다면 `bootstrap_silently: false`로 바꾸면 됩니다.

## 알림 / 관리 환경변수

### Telegram — 알림 + 관리

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

설정한 `TELEGRAM_CHAT_ID`에서 들어온 명령만 처리합니다.

### Discord 알림

- `DISCORD_WEBHOOK_URL`

### Discord 관리 — 선택

- `DISCORD_BOT_TOKEN`
- `DISCORD_ADMIN_USER_ID`

Discord 관리 기능을 쓰려면 Bot의 Message Content Intent도 활성화해야 합니다. 관리 기능이 필요 없으면 위 두 값은 비워둬도 됩니다.

### KakaoTalk (선택)

- `KAKAO_ACCESS_TOKEN`

KakaoTalk 기본 구현은 로그인한 본인의 `나와의 채팅`으로 보내는 방식입니다. 친구에게 보내기는 별도 권한/동의/쿼터 조건이 있으므로 기본 기능에 포함하지 않습니다.

`.env`와 `config.yaml`은 Git에 커밋되지 않도록 제외되어 있습니다.

## 데이터 보존

SQLite DB는 컨테이너 내부 `/data/sale_bot.sqlite3`에 있으며 Docker named volume `sale_bot_data`에 보존됩니다. 컨테이너를 삭제하거나 이미지를 다시 빌드해도 named volume을 직접 삭제하지 않는 한 데이터는 유지됩니다.

저장 내용:

- 감시항목 최대 3개
- 감시항목별 가격 상한/당근 지역/제외 키워드/일시정지 상태
- 매물 최초 발견 시각
- 마지막 확인 시각
- 현재 가격
- 가격 변경 이력
- 키워드/provider별 bootstrap 상태
- 이미 알림한 watch + provider + 매물 ID

## 수동 1회 점검

상시 실행 전에 한 번만 수집 테스트를 하려면:

```bash
docker compose run --rm sale-bot python -m sale_bot.main --once
```

로그에는 provider별로 다음 형태의 요약이 출력됩니다.

```text
[joongna] RX 9070 XT: fetched=20 matched=8 alerts=0 mode=baseline
```

## 코드 업데이트

```bash
git pull
docker compose up -d --build
```

polling 주기 같은 런타임 정책은 `config.yaml`에서 읽습니다. 감시 키워드/가격/지역/exclude는 최초 seed 이후 Telegram/Discord 명령으로 관리하는 것을 권장합니다.

## 개발 검증

GitHub Actions에서 다음을 자동 검증합니다.

- Ruff 정적 검사
- pytest 단위 테스트
- Docker 이미지 빌드
