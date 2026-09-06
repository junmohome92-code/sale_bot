# sale_bot

중고나라 · 당근 · 번개장터의 공개 검색 결과를 주기적으로 확인하고, 설정한 가격 범위에 들어오는 매물을 Telegram / Discord / KakaoTalk(선택)으로 알리는 개인용 가격 추적 봇입니다.

Ubuntu 홈서버에는 **Docker와 Docker Compose만 있으면 됩니다.** Python, Playwright, Chromium 등 실행 의존성은 이미지 안에 설치됩니다.

## 주요 기능

- 감시 키워드 최대 **3슬롯**
- 상품별 **최소가격 + 최대가격** 설정
- 제외 키워드(예: `삽니다`, `구매`, `매입`)
- 동일 watch + 사이트 + 매물 ID는 전달 성공 후 **최초 1회만 알림**
- 알림 채널이 없거나 일시 실패하면 알림 후보를 보존해 다음 검색에서 재시도
- 가격 범위 밖 매물도 가격 이력을 관측하므로 나중에 범위로 내려오면 실제 `가격 인하`로 판정
- 당근 다중 지역 및 **`지역명 전체` 자동 확장**
- SQLite 매물/가격 이력/감시 설정/알림 상태 저장
- Docker 상시 실행 및 서버 재부팅 후 자동 재시작
- 최초 검색 기존 매물을 조용히 기준선으로 잡는 bootstrap 모드

> 읽기 전용 검색/모니터링만 대상으로 합니다. 로그인·CAPTCHA·봇 차단 우회, 자동 채팅, 자동 구매는 구현하지 않습니다.

## 당근 지역 설정

특정 지역은 그대로 지정합니다.

```yaml
daangn_regions:
  - "대전광역시 유성구 봉명동"
  - "경기도 성남시 분당구 정자동"
```

넓은 범위는 이름 뒤에 `전체`를 붙입니다.

```yaml
daangn_regions:
  - "청주시 전체"
  - "대전시 전체"
  - "경기도 성남시 전체"
  - "서울특별시 마포구 전체"
```

`청주시 전체`만을 위한 하드코딩 목록은 사용하지 않습니다. 실행 시 당근의 현재 region resolver가 반환하는 계층(`name1/name2/name3`, 내부 region id)을 이용해 실제 검색 가능한 하위 지역을 발견하고 batch로 나눕니다.

동명이 겹치는 짧은 범위(예: `중구 전체`)가 여러 도시에 걸리면 임의 선택하지 않고 오류로 처리합니다. 이런 경우 `대전광역시 중구 전체`처럼 상위 지역을 포함해 주세요.

```yaml
# 넓은 지역의 하위 지역을 몇 묶음으로 나눌지
daangn_region_batches: 5
```

예를 들어 polling이 300초이고 5 batch이면 넓은 지역 전체 1회전은 대략 25분입니다. 개별로 지정한 지역은 매 cycle 검사합니다.

이전 설정명 `daangn_full_region_batches`도 호환되지만 새 설정은 `daangn_region_batches`를 권장합니다.

## config.yaml 예시

```yaml
poll_interval_seconds: 300
alert_on_first_seen: true
alert_on_price_increase: false
bootstrap_silently: true
request_timeout_seconds: 20
daangn_region_batches: 5

watches:
  - name: "닌텐도스위치2"
    query: "닌텐도스위치2"
    min_price: 500000
    max_price: 1200000
    exclude_keywords:
      - "삽니다"
      - "구매"
      - "매입"
    providers:
      - daangn
      - joongna
      - bunjang
    daangn_regions:
      - "청주시 전체"
      # - "대전시 전체"
      # - "경기도 성남시 전체"
```

`watches`는 SQLite DB가 처음 만들어질 때 seed됩니다. 그 뒤 실제 감시항목은 DB가 기준입니다. YAML의 감시 조건을 바꾼 뒤 Windows 테스트에서 새로 적용하려면 메뉴 7번으로 테스트 DB를 초기화합니다.

기존 DB는 시작 시 `min_price` 컬럼을 자동 추가하고, 같은 이름의 YAML seed 항목에 `min_price`가 있으면 기존 NULL 값에 한 번 backfill합니다.

## 알림 정책

- `bootstrap_silently: true`: 각 provider/당근 batch를 처음 정상 완료할 때 현재 조건 충족 매물을 기준선으로 저장하고 알림하지 않습니다.
- 당근 batch 중 일부 지역이 실패하면 그 batch는 `baseline-partial`로 남으며 완료 처리하지 않습니다.
- `alert_on_first_seen: true`: 활성 상태에서 새로 처음 관측되고 가격/제외 조건을 만족하는 매물을 알림 후보로 등록합니다.
- `alert_on_price_increase: false`: 가격 인상만으로 새 알림 후보를 만들지 않습니다.
- 가격 하락으로 조건 범위에 들어오는 경우는 알림 후보가 됩니다.
- 실제 알림 전송이 성공해야 중복방지 receipt를 소모합니다.

로그 예:

```text
[daangn] 닌텐도스위치2: fetched=22 matched=4 alerts=0 mode=baseline batch=1/5
```

부분 실패라면:

```text
[daangn] ... mode=baseline-partial batch=1/5 region_errors=1
```

## Telegram / Discord 관리 명령

```text
/add 상품명 | 최대가격 또는 최소~최대 | 당근지역(선택)
/list
/price ID 최대가격
/range ID 최소가격 최대가격
/region ID 지역1, 지역2, ...
/exclude ID add 단어
/exclude ID del 단어
/pause ID
/resume ID
/delete ID
/help
```

예:

```text
/add 스위치2 | 500000~900000 | 대전시 전체, 경기도 성남시 전체
/range 1 550000 850000
/region 1 대전시 전체
/list
```

지역을 `/region`으로 바꾸면 해당 watch의 **당근 bootstrap/batch/pending 상태만 초기화**합니다. 이미 성공적으로 보낸 매물의 receipt는 유지하므로 같은 매물 중복알림은 발생시키지 않습니다.

## Windows 테스트

저장소 ZIP을 받아 `sale_bot - sale test win` 폴더의 `SALE_TEST.bat`를 실행합니다.

```text
1. 최초 설치
2. 코드 테스트
3. 중고마켓 실제 검색 1회
4. 계속 실행
5. 검색 설정 열기 (config.yaml)
6. 텔레그램/디스코드 설정 열기 (.env)
7. 설정 변경 적용 / Windows 테스트 DB 초기화
8. 당근 현재 batch 지역/검색 진단
9. 당근 '전체' 지역 전수 해석 검증
0. 종료
```

- **8번**: 현재 batch만 실제 매물 검색까지 검사합니다.
- **9번**: `대전시 전체`, `경기도 성남시 전체` 같은 범위가 발견한 모든 하위 지역을 region id로 해석할 수 있는지 검사합니다. 매물 검색/DB/알림은 하지 않습니다.
- `config.yaml`의 watch 조건을 수정했다면 **7번 → 3번** 순서로 새 설정을 테스트합니다.

## Ubuntu 홈서버 배포

```bash
cd sale_bot
cp config.example.yaml config.yaml
cp .env.example .env

docker compose up -d --build
docker compose ps
docker compose logs -f --tail=100 sale-bot
```

`restart: unless-stopped`가 적용되어 Docker가 부팅 시 시작되는 서버에서는 재부팅 후 컨테이너도 자동으로 올라옵니다.

## 알림 / 관리 환경변수

### Telegram

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### Discord 알림

- `DISCORD_WEBHOOK_URL`

### Discord 관리

- `DISCORD_BOT_TOKEN`
- `DISCORD_ADMIN_USER_ID`

### KakaoTalk (선택)

- `KAKAO_ACCESS_TOKEN`

KakaoTalk 기본 구현은 로그인한 본인의 `나와의 채팅`으로 보내는 방식입니다.

`.env`와 `config.yaml`은 Git에 커밋되지 않도록 제외되어 있습니다.

## 데이터 보존

SQLite DB에는 다음을 저장합니다.

- 감시항목 최대 3개
- 최소/최대 가격, 당근 지역, 제외 키워드, 일시정지 상태
- 매물 최초/마지막 발견 시각
- 현재 가격 및 가격 변경 이력
- provider/당근 batch별 bootstrap 상태
- 전달 대기 중인 alert candidate
- 이미 전달한 watch + provider + 매물 ID receipt

Docker에서는 DB가 `/data/sale_bot.sqlite3`에 있고 named volume에 보존됩니다.

## 수동 1회 점검

```bash
docker compose run --rm sale-bot python -m sale_bot.main --once
```

## 코드 업데이트

```bash
git pull
docker compose up -d --build
```

## 개발 검증

GitHub Actions에서 자동 검증합니다.

- Ruff 정적 검사
- pytest 단위/회귀 테스트
- 루트와 Windows 테스트 복사본 핵심 코드 일치 여부
- Windows `SALE_TEST.bat` 실행 스모크
- Docker 이미지 빌드
