from pathlib import Path

import pytest

from financial_app.persistence.paths import data_dir, database_path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_default_data_dir_is_outside_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINANCIAL_APP_DATA_DIR", raising=False)
    assert not data_dir().resolve().is_relative_to(REPO_ROOT)


def test_data_dir_can_be_overridden_by_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    assert database_path() == tmp_path / "financial_app.sqlite3"
