"""A fund's TER, Distribution Policy and domicile (issue #42): the Instrument dialog and the Portfolio, without a
browser or the network."""

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import DistributionPolicy, InstrumentDraft
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_instruments
from financial_app.persistence.transactions import add_transaction
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
AKCJE_ZAGRANICZNE = 3


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
async def user(engine: Engine) -> AsyncIterator[User]:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        yield user


def _open_new_fund(user: User) -> None:
    user.find("Dodaj instrument").click()
    user.find(marker="instrument-name").clear().type("ETFBSPXPL")
    with user.scope(marker="instrument-dialog"):
        user.find(marker="instrument-class").click()
        user.find("Akcje zagraniczne").click()


async def test_user_enters_a_funds_ter_policy_and_domicile(user: User, engine: Engine) -> None:
    _open_new_fund(user)
    user.find(marker="instrument-ter").clear().type("0,075")
    user.find(marker="instrument-distribution-policy").click()
    user.find("Akumulacja").click()
    user.find(marker="instrument-domicile").clear().type("Irlandia")
    user.find("Zapisz").click()

    [saved] = list_instruments(engine)
    assert (saved.ter_percent, saved.distribution_policy, saved.domicile) == (
        Decimal("0.075"),
        DistributionPolicy.ACCUMULATING,
        "Irlandia",
    )
    with user.scope(marker="instruments"):
        await user.should_see(f"TER 0,075{NBSP}% · Akumulacja · Siedziba: Irlandia")
    user.find(marker="edit-instrument").click()
    await user.should_see("0,075")


async def test_a_fund_is_saved_without_its_details(user: User, engine: Engine) -> None:
    _open_new_fund(user)
    user.find("Zapisz").click()

    [saved] = list_instruments(engine)
    assert (saved.ter_percent, saved.distribution_policy, saved.domicile) == (None, None, "")


async def test_an_invalid_ter_is_reported_and_not_saved(user: User, engine: Engine) -> None:
    _open_new_fund(user)
    user.find(marker="instrument-ter").clear().type("120")
    user.find("Zapisz").click()

    await user.should_see("TER musi wynosić od 0 do mniej niż 100%.")
    assert list_instruments(engine) == []


def _held(engine: Engine, draft: InstrumentDraft) -> None:
    account = add_account(engine, AccountDraft("mBank IKE", "mBank", AccountType.IKE, ("PLN",)))
    instrument = add_instrument(engine, draft)
    add_transaction(engine, TransactionDraft(account.id, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(2000)))
    add_transaction(
        engine,
        buy_or_sell(account.id, date(2026, 1, 7), TransactionType.BUY, instrument.id, Decimal(10), Decimal(100)),
    )


async def test_a_clicked_position_shows_the_funds_details(engine: Engine) -> None:
    _held(
        engine,
        InstrumentDraft(
            "ETFBSPXPL",
            AKCJE_ZAGRANICZNE,
            "PLN",
            manual_price=Decimal(110),
            ter_percent=Decimal("0.5"),
            distribution_policy=DistributionPolicy.DISTRIBUTING,
            domicile="Polska",
        ),
    )

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/portfolio")
        user.find(marker="position-row").click()

        await user.should_see(marker="fund-details", content=f"TER 0,50{NBSP}% · Dystrybucja · Siedziba: Polska")


async def test_a_position_without_fund_details_shows_none(engine: Engine) -> None:
    _held(engine, InstrumentDraft("PZU", 2, "PLN", manual_price=Decimal(110)))

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/portfolio")
        user.find(marker="position-row").click()

        await user.should_not_see(marker="fund-details")
