"""Smoke test of the real entry point: one command builds the database and shows the window."""

from pathlib import Path

import pytest
from nicegui.testing import user_simulation

MAIN_FILE = Path(__file__).resolve().parents[1] / "main.py"


async def test_app_starts_with_database_in_data_dir_and_shows_dashboard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))

    async with user_simulation(main_file=MAIN_FILE) as user:
        await user.open("/")

        await user.should_see("Dashboard")
    assert (tmp_path / "financial_app.sqlite3").exists()
