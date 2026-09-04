from pathlib import Path

import win_menu


def test_reset_test_db_removes_sqlite_files(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    files = (
        data / "sale_bot-win.sqlite3",
        data / "sale_bot-win.sqlite3-shm",
        data / "sale_bot-win.sqlite3-wal",
    )
    for path in files:
        path.write_text("x", encoding="utf-8")

    monkeypatch.setattr(win_menu, "DB_FILES", files)
    win_menu.reset_test_db()

    assert all(not Path(path).exists() for path in files)
