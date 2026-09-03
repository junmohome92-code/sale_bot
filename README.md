# sale_bot

중고나라 · 당근 · 번개장터의 공개 검색 결과를 주기적으로 확인하고, 새 매물과 가격 변동을 Telegram / Discord / KakaoTalk(선택)으로 알리는 개인용 가격 추적 봇입니다.

## 목표

- 키워드별 최소/최대 가격 조건
- 제외 키워드(예: `삽니다`, `구매`, `매입`)
- 사이트별 독립 provider
- 새 매물 알림
- 가격 인하/변동 이력 저장
- SQLite 기반 중복 제거
- Telegram Bot API / Discord Webhook 알림
- KakaoTalk `나에게 보내기` 선택 지원
- Docker 상시 실행

> 이 프로젝트는 읽기 전용 검색/모니터링만 대상으로 합니다. 로그인·CAPTCHA·봇 차단 우회, 자동 채팅, 자동 구매는 구현하지 않습니다. 각 사이트의 이용약관과 접근 정책을 준수하고 과도한 요청을 피하세요.

## 현재 provider 전략

- **Daangn**: 공개 웹 검색 데이터 표면을 읽기 전용으로 사용. 지역을 설정할 수 있습니다.
- **Joongna**: 공개 검색 페이지를 읽고 상품 링크/가격을 추출합니다. 사이트 구조 변경 시 selector 수정이 필요할 수 있습니다.
- **Bunjang**: 공개 검색 페이지를 Playwright/Chromium으로 읽습니다. 공식 Open API는 파트너 계약 및 API 키가 필요한 별도 경로이므로 기본값으로 사용하지 않습니다.

## 빠른 시작

```bash
cp config.example.yaml config.yaml
cp .env.example .env
# config.yaml의 키워드/가격/지역을 수정
# .env에 Telegram 또는 Discord 자격정보 입력

docker compose up -d --build

docker compose logs -f sale-bot
```

## 설정 예시

```yaml
poll_interval_seconds: 300
alert_on_first_seen: true
alert_on_price_increase: false

watches:
  - name: "RX 9070 XT"
    query: "9070 xt"
    min_price: 500000
    max_price: 1200000
    exclude_keywords: ["삽니다", "구매", "매입"]
    providers: [daangn, joongna, bunjang]
    daangn_region: "청주시"
```

## 알림 환경변수

### Telegram

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### Discord

- `DISCORD_WEBHOOK_URL`

### KakaoTalk (선택)

- `KAKAO_ACCESS_TOKEN`

KakaoTalk 기본 구현은 로그인한 본인의 `나와의 채팅`으로 보내는 방식입니다. 친구에게 보내기는 별도 권한/동의/쿼터 조건이 있으므로 이 MVP에는 포함하지 않습니다.

## 데이터

SQLite DB는 기본적으로 `/data/sale_bot.sqlite3`에 저장됩니다.

- 매물 최초 발견 시각
- 마지막 확인 시각
- 현재 가격
- 가격 변경 이력
- 마지막 알림 이벤트

컨테이너를 재시작해도 `sale_bot_data` 볼륨에 유지됩니다.

## 개발 명령

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
playwright install chromium
pytest
python -m sale_bot.main --once
```
