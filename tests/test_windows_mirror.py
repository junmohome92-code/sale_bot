from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "sale_bot - sale test win"


def test_windows_runtime_source_matches_root():
    files = [
        "admin.py",
        "config.py",
        "main.py",
        "models.py",
        "notifiers.py",
        "providers.py",
        "storage.py",
    ]
    for name in files:
        root_file = ROOT / "src" / "sale_bot" / name
        windows_file = WINDOWS / "src" / "sale_bot" / name
        assert windows_file.read_bytes() == root_file.read_bytes(), name


def test_windows_test_and_example_config_match_root():
    for relative in [
        Path("tests/test_core.py"),
        Path("tests/test_providers.py"),
        Path("config.example.yaml"),
        Path("pyproject.toml"),
        Path("README.md"),
    ]:
        assert (WINDOWS / relative).read_bytes() == (ROOT / relative).read_bytes(), str(relative)
