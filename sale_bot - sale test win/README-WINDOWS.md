# sale_bot - sale test win

이 디렉토리는 원본 `sale_bot`을 건드리지 않고 Windows에서 설치/테스트/실검색을 확인하기 위한 복제본입니다.

## 준비물

- Windows 10/11
- Python 3.12 이상
- PowerShell
- 인터넷 연결

## 1. 최초 설치

PowerShell에서 이 디렉토리로 이동한 뒤:

```powershell
powershell -ExecutionPolicy Bypass -File .\win.ps1 setup
```

자동으로 다음 작업을 합니다.

- `config.example.yaml` -> `config.yaml` 생성
- `.env.example` -> `.env` 생성
- `.venv` 생성
- Python 패키지 설치
- Playwright Chromium 설치
- `data` 폴더 생성

## 2. 단위 테스트

```powershell
powershell -ExecutionPolicy Bypass -File .\win.ps1 test
```

실행 항목:

- Ruff
- pytest

## 3. 1회 실검색 테스트

`.env`와 `config.yaml`을 필요한 값으로 수정한 뒤:

```powershell
powershell -ExecutionPolicy Bypass -File .\win.ps1 once
```

이 명령은 한 polling cycle만 실행하고 종료합니다.

Windows 테스트 DB는 다음 위치를 사용합니다.

```text
data\sale_bot-win.sqlite3
```

따라서 Ubuntu Docker 운영 DB와 섞이지 않습니다.

## 4. Windows에서 계속 실행

```powershell
powershell -ExecutionPolicy Bypass -File .\win.ps1 run
```

종료는 `Ctrl + C`입니다.

## 환경변수

`.env`에서 필요한 값을 설정합니다.

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DISCORD_WEBHOOK_URL=
DISCORD_BOT_TOKEN=
DISCORD_ADMIN_USER_ID=
KAKAO_ACCESS_TOKEN=
```

`win.ps1`이 `.env`를 읽어서 현재 PowerShell 프로세스에만 적용합니다.

## 주의

- 원본 Ubuntu/Docker 운영본과 별도 테스트용입니다.
- Chromium은 번개장터 검색에만 사용됩니다.
- 실검색은 사이트 구조/접근정책/네트워크 상태에 따라 실패할 수 있습니다.
- 로그인, CAPTCHA, 봇 차단 우회 기능은 포함하지 않습니다.
