"""Ustawienia > Import z XTB i uzgadnianie (L-17, #271): the step-by-step window matching, resolving and applying,
without a browser."""

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
from financial_app.domain.formatting import format_pln
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.transactions import COVERING_COMMENT, Origin, TransactionDraft, TransactionType
from financial_app.persistence.accounts import add_account
from financial_app.persistence.contribution_limits import set_limits
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes, list_instruments
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


async def load(user: User, path: Path) -> None:
    """Open the import window, read its instructions and load ``path``."""
    user.find(marker="settings-section-import").click()
    user.find(marker="xtb-open").click()
    await user.should_see(marker="xtb-step-1")
    await user.should_see("Po jednym zestawieniu na rachunek")
    user.find(marker="xtb-next").click()
    await user.should_see(marker="xtb-step-2")
    user.find(marker="xtb-path").type(str(path))
    user.find(marker="xtb-load").click()
    await user.should_see(marker="xtb-step-3")


def forward(user: User, steps: int) -> None:
    for _ in range(steps):
        user.find(marker="xtb-next").click()


def choose(user: User, marker: str, value: object) -> None:
    user.find(marker=marker, kind=ui.select).elements.pop().set_value(value)


def new_instrument(user: User) -> None:
    choose(user, "xtb-instrument-XTB.PL", NEW)
    user.find(marker="instrument-name").type("XTB")
    choose(user, "instrument-class", 1)
    user.find("Zapisz").click()


async def test_the_window_guides_through_the_import_and_proposes_the_missing_deposit(
    engine: Engine, user: User, tmp_path: Path
) -> None:
    ike = add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN",)))
    shares = next(c for c in list_asset_classes(engine) if c.name == "Akcje polskie")
    add_instrument(engine, InstrumentDraft("XTB", shares.id, "PLN"))
    mine = add_transaction(engine, TransactionDraft(ike.id, date(2026, 10, 9), TransactionType.DEPOSIT, Decimal(400)))
    # Exported from the day of the purchase: the Deposit that paid for it is not in the statement
    path = write_statement(
        tmp_path / "IKE.xlsx",
        IKE_NUMBER,
        [
            op("Stock purchase", datetime(2026, 10, 9, 7), -973.0, "101", "OPEN BUY XTB.PL 7 @ 139.00", "XTB.PL",
               "XTB", "9"),
            op("Deposit", datetime(2026, 10, 10, 8), 100.0, "102"),
        ],
    )  # fmt: skip

    await load(user, path)
    # The one IKE Account is suggested and the ticker matched by name, so the next step follows
    assert user.find(marker="xtb-next", kind=ui.button).elements.pop().enabled
    forward(user, 1)

    await user.should_see(marker="xtb-step-4")
    await user.should_see("tylko w XTB: 2, tylko w aplikacji: 1")
    await user.should_see(marker="xtb-no-different")
    forward(user, 1)

    await user.should_see(marker="xtb-step-5")
    await user.should_see(marker="xtb-item")
    forward(user, 1)

    # The entered Deposit XTB lacks is deleted by default; kept, it pays for part of the purchase
    await user.should_see(marker="xtb-step-6")
    user.find(marker=f"xtb-choice-mine-{mine.id}", kind=ui.toggle).elements.pop().set_value("mine")
    forward(user, 1)

    await user.should_see(marker="xtb-step-7")
    await user.should_see(marker=f"xtb-deposits-{ike.id}")
    await user.should_see(f"09.10.2026: {format_pln(Decimal('573'))}")
    forward(user, 1)

    await user.should_see(marker="xtb-step-8")
    await user.should_see("Tylko w XTB: dodane 2, pominięte 0. Tylko w aplikacji: usunięte 0, zostawione 1.")
    await user.should_see(marker="xtb-deposits-summary")
    await user.should_see(marker="xtb-hints")
    user.find(marker="xtb-apply").click()

    saved = list_transactions(engine)
    assert mine in saved
    [covering] = [t for t in saved if t.comment == COVERING_COMMENT]
    assert (covering.account_id, covering.date, covering.actual_amount) == (ike.id, date(2026, 10, 9), Decimal(573))
    assert len(saved) == 4
    await user.should_see(marker="xtb-done")


async def test_a_new_instrument_for_a_ticker_then_the_statement_is_added(
    engine: Engine, statement: Path, user: User
) -> None:
    ike = add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN",)))
    await load(user, statement)
    await user.should_see(marker="xtb-instrument-XTB.PL")
    assert not user.find(marker="xtb-next", kind=ui.button).elements.pop().enabled

    choose(user, "xtb-instrument-XTB.PL", NEW)
    assert user.find(marker="instrument-search", kind=ui.input).elements.pop().value == "XTB.WA"
    user.find(marker="instrument-name").type("XTB")
    choose(user, "instrument-class", 1)
    user.find("Zapisz").click()

    forward(user, 1)
    await user.should_see(marker="xtb-summary")
    await user.should_see("tylko w XTB: 2")
    forward(user, 3)
    await user.should_see(marker="xtb-no-deposits")
    forward(user, 1)
    user.find(marker="xtb-apply").click()

    saved = list_transactions(engine)
    assert [(t.transaction_type, t.account_id, t.origin) for t in saved] == [
        (TransactionType.BUY, ike.id, Origin.BROKER),
        (TransactionType.DEPOSIT, ike.id, Origin.BROKER),
    ]
    assert [i.name for i in list_instruments(engine)] == ["XTB"]
    for _ in range(4):
        user.find(marker="xtb-back").click()
    await user.should_see("już uzgodnione: 2")


async def test_keeping_an_entered_deposit_xtb_does_not_have(engine: Engine, statement: Path, user: User) -> None:
    ike = add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN",)))
    mine = add_transaction(engine, TransactionDraft(ike.id, date(2026, 5, 9), TransactionType.DEPOSIT, Decimal(500)))
    await load(user, statement)
    choose(user, "xtb-account-" + IKE_NUMBER, "skip")
    forward(user, 1)
    await user.should_see("tylko w XTB: 0, tylko w aplikacji: 0")
    user.find(marker="xtb-back").click()
    choose(user, "xtb-account-" + IKE_NUMBER, ike.id)
    new_instrument(user)
    forward(user, 1)

    await user.should_see("tylko w aplikacji: 1")
    forward(user, 2)
    user.find(marker=f"xtb-choice-mine-{mine.id}", kind=ui.toggle).elements.pop().set_value("mine")
    forward(user, 2)
    user.find(marker="xtb-apply").click()

    assert mine in list_transactions(engine)
    assert len(list_transactions(engine)) == 3
    user.find(marker="xtb-back").click()
    user.find(marker="xtb-back").click()
    await user.should_see(marker="xtb-no-mine-only")


async def test_applying_deposits_over_the_contribution_limit_warns_once(
    engine: Engine, statement: Path, user: User
) -> None:
    ike = add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN",)))
    set_limits(engine, 2026, {AccountType.IKE: Decimal(500)})
    await load(user, statement)
    await user.should_see(marker="xtb-instrument-XTB.PL")
    new_instrument(user)
    forward(user, 5)
    await user.should_see(marker="xtb-apply")

    user.find(marker="xtb-apply").click()

    await user.should_see("IKE 2026: przekroczono limit wpłat o 500,00\N{NO-BREAK SPACE}zł.")
    await user.should_see(
        marker="limit-paid-2026-ike", content="wpłacono 1\N{NO-BREAK SPACE}000,00\N{NO-BREAK SPACE}zł"
    )
    assert ike.id in {t.account_id for t in list_transactions(engine)}


async def test_a_sale_above_what_was_bought_waits_for_its_correction(
    engine: Engine, user: User, tmp_path: Path
) -> None:
    add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN",)))
    shares = next(c for c in list_asset_classes(engine) if c.name == "Akcje polskie")
    add_instrument(engine, InstrumentDraft("XTB", shares.id, "PLN"))
    path = write_statement(
        tmp_path / "IKE.xlsx",
        IKE_NUMBER,
        [
            op("IKE deposit", datetime(2026, 10, 8, 21, 14), 1000.0, "100"),
            op("Stock purchase", datetime(2026, 10, 9, 7), -973.0, "101", "OPEN BUY XTB.PL 7 @ 139.00", "XTB.PL",
               "XTB", "9"),
            op("Stock sell", datetime(2026, 10, 10, 7), 1050.0, "102", "CLOSE BUY XTB.PL 7.5 @ 140.00", "XTB.PL",
               "XTB", "9"),
        ],
    )  # fmt: skip
    await load(user, path)
    forward(user, 5)

    await user.should_see(marker="xtb-corrections-missing")
    assert not user.find(marker="xtb-apply", kind=ui.button).elements.pop().enabled
    user.find(marker="xtb-back").click()

    with user.scope(marker="xtb-corrections-1"):
        await user.should_see("Brakuje 0,5 szt.")
    await user.should_see(marker="xtb-corrections-large-1")
    user.find(marker="xtb-corrections-fix-1", kind=ui.radio).elements.pop().set_value("trim")
    forward(user, 1)
    user.find(marker="xtb-apply").click()
    await user.should_see("Uzgodniono z XTB")
    sale = next(t for t in list_transactions(engine) if t.transaction_type is TransactionType.SELL)
    assert (sale.quantity, sale.actual_amount) == (Decimal(7), Decimal("1050.00"))
