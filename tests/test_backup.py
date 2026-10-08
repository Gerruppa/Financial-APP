import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from financial_app.persistence.backup import KEEP_BACKUPS, backup_database
from financial_app.persistence.db import init_db

START = datetime(2026, 10, 8, 9, 0, 0)


def make_database(path: Path) -> Path:
    init_db(path).dispose()
    return path


def test_backup_copies_the_database_into_the_backups_folder(tmp_path: Path) -> None:
    db_file = make_database(tmp_path / "app.sqlite3")
    backups = tmp_path / "backups"

    copy = backup_database(db_file, backups, now=START)

    assert copy is not None
    assert copy.parent == backups
    with sqlite3.connect(copy) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "app_settings" in tables


def test_no_backup_when_the_database_does_not_exist_yet(tmp_path: Path) -> None:
    backups = tmp_path / "backups"

    assert backup_database(tmp_path / "missing.sqlite3", backups, now=START) is None
    assert not backups.exists()


def test_the_31st_backup_removes_the_oldest(tmp_path: Path) -> None:
    db_file = make_database(tmp_path / "app.sqlite3")
    backups = tmp_path / "backups"
    copies = [backup_database(db_file, backups, now=START + timedelta(days=day)) for day in range(KEEP_BACKUPS + 1)]

    remaining = sorted(backups.iterdir())

    assert KEEP_BACKUPS == 30
    assert len(remaining) == KEEP_BACKUPS
    assert copies[0] not in remaining
    assert remaining == sorted(copy for copy in copies[1:] if copy is not None)


def test_two_starts_within_the_same_second_keep_both_copies(tmp_path: Path) -> None:
    db_file = make_database(tmp_path / "app.sqlite3")
    backups = tmp_path / "backups"

    first = backup_database(db_file, backups, now=START)
    second = backup_database(db_file, backups, now=START)

    assert first != second
    assert len(list(backups.iterdir())) == 2


def test_rotation_ignores_unrelated_files(tmp_path: Path) -> None:
    db_file = make_database(tmp_path / "app.sqlite3")
    backups = tmp_path / "backups"
    backups.mkdir()
    keepsake = backups / "notes.txt"
    keepsake.write_text("mine")

    for day in range(KEEP_BACKUPS + 2):
        backup_database(db_file, backups, now=START + timedelta(days=day))

    assert keepsake.exists()
