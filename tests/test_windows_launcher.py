from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "sale_bot - sale test win"


def test_windows_folder_does_not_duplicate_runtime_source():
    assert not (WINDOWS / "src").exists()
    assert not (WINDOWS / "tests").exists()
    assert not (WINDOWS / "pyproject.toml").exists()


def test_windows_launcher_installs_and_tests_root_project():
    script = (WINDOWS / "win.ps1").read_text(encoding="utf-8")
    assert "$RepoRoot" in script
    assert "pip install -e" in script
    assert 'Join-Path $RepoRoot "src"' in script
    assert 'Join-Path $RepoRoot "tests"' in script


def test_windows_menu_keeps_simple_launcher_flow():
    menu = (WINDOWS / "win_menu.py").read_text(encoding="utf-8")
    assert "Windows 테스트 DB 완전 초기화" in menu
    assert "Telegram /menu" in menu
    assert "당근 '전체' 지역 전수 해석 검증" in menu
