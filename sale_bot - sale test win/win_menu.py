import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_FILES = (
    ROOT / "data" / "sale_bot-win.sqlite3",
    ROOT / "data" / "sale_bot-win.sqlite3-shm",
    ROOT / "data" / "sale_bot-win.sqlite3-wal",
)


def run_ps(action: str) -> None:
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "win.ps1"),
            action,
        ],
        cwd=ROOT,
        check=False,
    )


def run_daangn_diag(*, all_regions: bool = False) -> None:
    python_exe = ROOT / ".venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
        print("먼저 1번 '최초 설치'를 실행해주세요.")
        return
    args = [str(python_exe), str(ROOT / "daangn_diag.py")]
    if all_regions:
        args.append("--all-regions")
    subprocess.run(args, cwd=ROOT, check=False)


def open_file(path: Path, source: Path) -> None:
    if not path.exists():
        path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    os.startfile(path)


def reset_test_db() -> None:
    deleted = False
    for path in DB_FILES:
        if path.exists():
            path.unlink()
            deleted = True
    if deleted:
        print("Windows 테스트 DB를 초기화했습니다.")
        print("다음 3번/4번 실행에서 config.yaml의 감시 설정을 새로 적용합니다.")
    else:
        print("초기화할 Windows 테스트 DB가 없습니다.")
        print("다음 실행에서 config.yaml 설정이 새로 seed됩니다.")


def main() -> None:
    os.chdir(ROOT)
    while True:
        os.system("cls")
        print("=" * 48)
        print("       sale_bot - sale test win")
        print("=" * 48)
        print()
        print("  1. 최초 설치")
        print("  2. 코드 테스트")
        print("  3. 중고마켓 실제 검색 1회")
        print("  4. 계속 실행")
        print("  5. 검색 설정 열기 (config.yaml)")
        print("  6. 텔레그램/디스코드 설정 열기 (.env)")
        print("  7. 설정 변경 적용 / Windows 테스트 DB 초기화")
        print("  8. 당근 현재 batch 지역/검색 진단")
        print("  9. 당근 '전체' 지역 전수 해석 검증")
        print("  0. 종료")
        print()
        choice = input("번호를 선택하세요: ").strip()

        if choice == "1":
            run_ps("setup")
        elif choice == "2":
            run_ps("test")
        elif choice == "3":
            run_ps("once")
        elif choice == "4":
            run_ps("run")
        elif choice == "5":
            open_file(ROOT / "config.yaml", ROOT / "config.example.yaml")
            print("설정을 바꾼 뒤 기존 테스트 DB에도 적용하려면 메뉴 7번을 실행하세요.")
            input("Enter를 누르면 메뉴로 돌아갑니다.")
            continue
        elif choice == "6":
            open_file(ROOT / ".env", ROOT / ".env.example")
            continue
        elif choice == "7":
            reset_test_db()
        elif choice == "8":
            run_daangn_diag()
        elif choice == "9":
            run_daangn_diag(all_regions=True)
        elif choice == "0":
            return
        else:
            input("잘못된 번호입니다. Enter를 누르세요.")
            continue

        input("\n작업이 끝났습니다. Enter를 누르면 메뉴로 돌아갑니다.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
