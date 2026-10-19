from pathlib import Path

import pytest

from financial_app.persistence import paths
from financial_app.persistence.paths import adopt_legacy_data_dir, data_dir, database_path, move_legacy_data_dir

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_default_data_dir_is_outside_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINANCIAL_APP_DATA_DIR", raising=False)
    assert not data_dir().resolve().is_relative_to(REPO_ROOT)


def test_data_dir_can_be_overridden_by_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    assert database_path() == tmp_path / "financial_app.sqlite3"


def test_default_data_dir_is_named_after_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINANCIAL_APP_DATA_DIR", raising=False)
    assert data_dir().name == "KAPITA"


def test_legacy_data_dir_moves_to_the_new_name(tmp_path: Path) -> None:
    legacy, current = tmp_path / "FinancialApp", tmp_path / "KAPITA"
    legacy.mkdir()
    (legacy / "financial_app.sqlite3").write_text("data")

    move_legacy_data_dir(legacy, current)

    assert not legacy.exists()
    assert (current / "financial_app.sqlite3").read_text() == "data"


def test_existing_new_data_dir_is_never_overwritten(tmp_path: Path) -> None:
    legacy, current = tmp_path / "FinancialApp", tmp_path / "KAPITA"
    legacy.mkdir()
    (legacy / "financial_app.sqlite3").write_text("old")
    current.mkdir()
    (current / "financial_app.sqlite3").write_text("new")

    move_legacy_data_dir(legacy, current)

    assert (current / "financial_app.sqlite3").read_text() == "new"
    assert (legacy / "financial_app.sqlite3").read_text() == "old"


def test_nothing_happens_without_a_legacy_data_dir(tmp_path: Path) -> None:
    move_legacy_data_dir(tmp_path / "FinancialApp", tmp_path / "KAPITA")
    assert not (tmp_path / "KAPITA").exists()


@pytest.mark.parametrize("override", ["elsewhere", ""])
def test_adopting_moves_only_the_default_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, override: str) -> None:
    moves: list[tuple[Path, Path]] = []
    monkeypatch.setattr(paths, "move_legacy_data_dir", lambda legacy, current: moves.append((legacy, current)))
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path) if override else "")

    adopt_legacy_data_dir()

    # An empty override means the default folder, as for data_dir()
    assert [current.name for _, current in moves] == ([] if override else ["KAPITA"])
