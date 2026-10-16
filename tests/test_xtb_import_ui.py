"""Ustawienia > Import z XTB i uzgadnianie (L-17): matching, resolving and applying, without a browser."""

from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.transactions import Origin, TransactionDraft, TransactionType
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell
from financial_app.ui.xtb_import import NEW
from xtb_rows import op, write_statement

IKE_NUMBER = "54925231"


class FixedNbp(NbpRates):
    def __init__(self, engine: Engine) -> None:
        super().__init__(engine, fetch=lambda url: None, today=lambda: date(2026, 10, 13))

    def before(self, currency: str, day: date) -> NbpRate:
        return NbpRate(currency, Decimal("3.7000"), date(2026, 10, 8), "195/A/NBP/2026")


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def statement(tmp_path: Path) -> Path:
    return write_statement(
        tmp_path / "IKE.xlsx",
        IKE_NUMBER,
        [
            op("IKE deposit", datetime(2026, 10, 8, 21, 14), 1000.0, "100",
               "Transfer in operation on account with id 1"),
            op("Stock purchase", datetime(2026, 10, 9, 7), -973.0, "101", "OPEN BUY XTB.PL 7 @ 139.00", "XTB.PL",
               "XTB", "9"),
        ],
    )  # fmt: skip


@pytest.fixture
async def user(engine: Engine) -> AsyncIterator[User]:
    async with user_simulation(lambda: build_shell(engine, FixedNbp(engine))) as user:
        await user.open("/ustawienia")
        yield user


def load(user: User, path: Path) -> None:
    user.find(marker="xtb-path").type(str(path))
    user.find(marker="xtb-load").click()


async def test_a_new_instrument_for_a_ticker_then_the_statement_is_added(
    engine: Engine, statement: Path, user: User
) -> None:
    ike = add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN",)))
    load(user, statement)
    await user.should_see(marker="xtb-instrument-XTB.PL")
    await user.should_not_see(marker="xtb-apply")

    user.find(marker="xtb-instrument-XTB.PL", kind=ui.select).elements.pop().set_value(NEW)
    assert user.find(marker="instrument-search", kind=ui.input).elements.pop().value == "XTB.WA"
    user.find(marker="instrument-name").type("XTB")
    user.find(marker="instrument-class", kind=ui.select).elements.pop().set_value(1)
    user.find("Zapisz").click()

    await user.should_see(marker="xtb-summary")
    await user.should_see("tylko w XTB: 2")
    user.find(marker="xtb-apply").click()

    saved = list_transactions(engine)
    assert [(t.transaction_type, t.account_id, t.origin) for t in saved] == [
        (TransactionType.BUY, ike.id, Origin.BROKER),
        (TransactionType.DEPOSIT, ike.id, Origin.BROKER),
    ]
    assert [i.name for i in list_instruments(engine)] == ["XTB"]
    await user.should_see("już uzgodnione: 2")


async def test_keeping_an_entered_deposit_xtb_does_not_have(engine: Engine, statement: Path, user: User) -> None:
    ike = add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN",)))
    mine = add_transaction(engine, TransactionDraft(ike.id, date(2026, 5, 9), TransactionType.DEPOSIT, Decimal(500)))
    load(user, statement)
    user.find(marker="xtb-account-" + IKE_NUMBER, kind=ui.select).elements.pop().set_value("skip")
    await user.should_see("tylko w XTB: 0, tylko w aplikacji: 0")
    user.find(marker="xtb-account-" + IKE_NUMBER, kind=ui.select).elements.pop().set_value(ike.id)
    user.find(marker="xtb-instrument-XTB.PL", kind=ui.select).elements.pop().set_value(NEW)
    user.find(marker="instrument-name").type("XTB")
    user.find(marker="instrument-class", kind=ui.select).elements.pop().set_value(1)
    user.find("Zapisz").click()

    await user.should_see("tylko w aplikacji: 1")
    user.find(marker=f"xtb-choice-mine-{mine.id}", kind=ui.toggle).elements.pop().set_value("mine")
    user.find(marker="xtb-apply").click()

    assert mine in list_transactions(engine)
    assert len(list_transactions(engine)) == 3
    await user.should_see("tylko w aplikacji: 0")
