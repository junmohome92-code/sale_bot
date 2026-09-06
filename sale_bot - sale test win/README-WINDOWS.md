# sale_bot - sale test win

Windows에서 원본과 같은 sale_bot 코드를 쉽게 설치·검증·실검색하기 위한 테스트 폴더입니다.

가장 쉬운 사용법은 **`SALE_TEST.bat`를 더블클릭**하는 것입니다.

## 메뉴

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

### 처음 사용할 때

1. `1` 최초 설치
2. `5`에서 검색 조건 수정 후 `Ctrl + S` 저장
3. `7` 설정 적용
4. `9` 당근 `전체` 지역을 사용한다면 전체 지역 해석 검증
5. `3` 실제 검색 1회
6. 이상 없으면 `4` 계속 실행

`config.yaml`의 watch 설정은 DB가 처음 만들어질 때 적용됩니다. 이미 테스트 DB가 있는 상태에서 가격·키워드·지역 설정을 바꿨다면 **7번을 실행해야 새 YAML watch 설정이 다시 적용**됩니다.

## 당근 지역

```yaml
daangn_region_batches: 5

daangn_regions:
  - "청주시 전체"
  # - "대전시 전체"
  # - "경기도 성남시 전체"
  # - "대전광역시 유성구 봉명동"
```

`지역명 전체`는 청주시 전용 하드코딩이 아니라 당근의 현재 region 계층에서 하위 지역을 자동 발견합니다.

- **8번**: 현재 batch의 지역 해석 + 실제 검색 결과를 확인합니다.
- **9번**: 발견된 전체 하위지역을 전부 region id로 해석할 수 있는지만 확인합니다. 매물/DB/알림은 건드리지 않습니다.

동명이 많은 짧은 입력은 임의 선택하지 않습니다. `중구 전체`처럼 애매하면 `대전광역시 중구 전체`처럼 상위 지역을 같이 적어주세요.

## 가격 설정

```yaml
min_price: 500000
max_price: 1200000
```

두 값 모두 실제 DB에 저장됩니다. 기존 테스트 DB도 새 버전 실행 시 `min_price` 컬럼이 자동 추가됩니다.

## 테스트 DB

```text
data\sale_bot-win.sqlite3
```

Ubuntu/Docker 운영 DB와 분리되어 있습니다.

## 알림 설정

6번 메뉴에서 `.env`를 열어 필요한 값만 설정합니다.

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DISCORD_WEBHOOK_URL=
DISCORD_BOT_TOKEN=
DISCORD_ADMIN_USER_ID=
KAKAO_ACCESS_TOKEN=
```

알림 채널이 설정되지 않아도 매물과 가격 이력은 저장됩니다. 알림 조건에 들어온 후보는 전달 성공 전까지 보존됩니다.

## 직접 PowerShell로 실행할 경우

```powershell
powershell -ExecutionPolicy Bypass -File .\win.ps1 setup
powershell -ExecutionPolicy Bypass -File .\win.ps1 test
powershell -ExecutionPolicy Bypass -File .\win.ps1 once
powershell -ExecutionPolicy Bypass -File .\win.ps1 run
```

계속 실행 종료는 `Ctrl + C`입니다.

## 주의

- Chromium은 번개장터 검색에 사용됩니다.
- 공개 사이트 구조/접근 정책/네트워크 상태가 바뀌면 실검색이 실패할 수 있습니다.
- 로그인, CAPTCHA, 봇 차단 우회, 자동 구매 기능은 포함하지 않습니다.
