"""Saving Valuation Snapshots (issue #115, ADR-0008): one a calendar day per View Scope, the newest of an earlier day
read back, gone with their Account."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.valuation_snapshots import Figures, ValuationSnapshot
from financial_app.persistence.accounts import add_account, delete_account
from financial_app.persistence.db import init_db
from financial_app.persistence.valuation_snapshots import save_snapshot, snapshot_before


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _figures(value: int, net_deposits: int) -> Figures:
    return Figures(Decimal(value), Decimal(net_deposits))


def test_a_snapshot_keeps_total_and_each_account(engine: Engine) -> None:
    account = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id
    taken_at = datetime(2026, 10, 9, 18, 2)

    save_snapshot(engine, taken_at, {None: _figures(1500, 1000), account: _figures(1500, 1200)})

    assert snapshot_before(engine, date(2026, 10, 16), None) == ValuationSnapshot(taken_at, _figures(1500, 1000))
    assert snapshot_before(engine, date(2026, 10, 16), account) == ValuationSnapshot(taken_at, _figures(1500, 1200))


def test_the_reference_is_the_newest_snapshot_of_an_earlier_day(engine: Engine) -> None:
    save_snapshot(engine, datetime(2026, 10, 2, 18, 0), {None: _figures(100, 100)})
    save_snapshot(engine, datetime(2026, 10, 9, 18, 2), {None: _figures(200, 100)})
    save_snapshot(engine, datetime(2026, 10, 16, 9, 0), {None: _figures(300, 100)})

    assert snapshot_before(engine, date(2026, 10, 16), None) == ValuationSnapshot(
        datetime(2026, 10, 9, 18, 2), _figures(200, 100)
    )
    assert snapshot_before(engine, date(2026, 10, 2), None) is None


def test_a_later_refresh_the_same_day_replaces_that_days_snapshot(engine: Engine) -> None:
    account = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id
    save_snapshot(engine, datetime(2026, 10, 9, 9, 0), {None: _figures(100, 100), account: _figures(100, 100)})

    save_snapshot(engine, datetime(2026, 10, 9, 18, 2), {None: _figures(200, 100)})

    assert snapshot_before(engine, date(2026, 10, 10), None) == ValuationSnapshot(
        datetime(2026, 10, 9, 18, 2), _figures(200, 100)
    )
    assert snapshot_before(engine, date(2026, 10, 10), account) is None


def test_deleting_an_account_deletes_its_snapshots(engine: Engine) -> None:
    account = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id
    save_snapshot(engine, datetime(2026, 10, 9, 18, 2), {None: _figures(0, 0), account: _figures(0, 0)})

    delete_account(engine, account)
    again = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id

    assert snapshot_before(engine, date(2026, 10, 16), again) is None
    assert snapshot_before(engine, date(2026, 10, 16), None) is not None
