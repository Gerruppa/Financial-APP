"""The made-up Portfolio of ``main.py --demo`` and the start options that choose it."""

import tempfile
from datetime import date
from pathlib import Path

import pytest
from nicegui.testing import user_simulation
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from financial_app import app
from financial_app.persistence.db import migrate
from financial_app.persistence.paths import DATA_DIR_ENV, database_path
from financial_app.persistence.transactions import list_transactions
from financial_app.sources.demo_data import seed_demo_data
from financial_app.ui.shell import build_shell

TODAY = date(2026, 10, 19)


@pytest.fixture
def engine() -> Engine:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    migrate(engine)
    return engine


def test_the_demo_holds_a_year_of_transactions_up_to_today(engine: Engine) -> None:
    seed_demo_data(engine, TODAY)

    days = [transaction.date for transaction in list_transactions(engine)]
    assert len(days) == 10
    assert min(days) == date(2025, 10, 24) and max(days) < TODAY


async def test_the_demo_portfolio_shows_its_made_up_instruments(engine: Engine) -> None:
    seed_demo_data(engine, TODAY)

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/portfolio")

        await user.should_see("DEMO ETF Świat")


def test_the_demo_database_is_fresh_in_temp_and_leaves_the_real_data_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    # Set here so monkeypatch restores it after start_demo_database overrides it
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "real"))

    app.start_demo_database()
    # A second start begins again from an empty database instead of failing on the Accounts already there
    app.start_demo_database()

    assert database_path() == tmp_path / "KAPITA-demo" / "financial_app.sqlite3"
    assert not (tmp_path / "real").exists()


def test_the_start_options_default_to_the_native_window() -> None:
    assert not app.parse_args([]).browser and not app.parse_args([]).demo
    assert app.parse_args(["--demo", "--port", "8090"]).port == 8090
    # pytest's own options, seen when the startup tests run main.py, are ignored
    assert not app.parse_args(["-n", "auto", "--testmon"]).browser
