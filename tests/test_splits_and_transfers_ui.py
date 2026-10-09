"""Splits, Cash Transfers and Security Transfers in the transaction dialog and on Transakcje (issue #19)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from nicegui.testing.user_interaction import UserInteraction
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.lots import open_positions
from financial_app.domain.transactions import SplitRatio, TransactionType, buy_or_sell, cash_balances
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell

NBSP = "\xa0"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def ike(engine: Engine) -> int:
    return add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id


@pytest.fixture
def xtb(engine: Engine) -> int:
    return add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id


@pytest.fixture
def pzu(engine: Engine) -> int:
    asset_class = list_asset_classes(engine)[1]
    return add_instrument(engine, InstrumentDraft("PZU", asset_class.id, "PLN", manual_price=Decimal(50))).id


def _bought(engine: Engine, account: int, instrument: int) -> None:
    add_transaction(
        engine, buy_or_sell(account, date(2026, 1, 2), TransactionType.BUY, instrument, Decimal(10), Decimal(40))
    )


def _shell(engine: Engine) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: "", today=lambda: date(2026, 1, 8)))


def _choose(user: User, marker: str, option: str) -> None:
    user.find(marker=marker).click()
    user.find(option).click()


def _start(user: User, kind: str, account: str = "IKE") -> None:
    user.find(marker="add-transaction").click()
    _choose(user, "transaction-type", kind)
    _choose(user, "transaction-account", account)
    user.find(marker="transaction-date").clear().type("07.01.2026")


async def test_split_rescales_the_position_and_shows_its_ratio(engine: Engine, ike: int, pzu: int) -> None:
    _bought(engine, ike, pzu)
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")  # the Transakcje list would also offer PZU to click
        _start(user, "Split")
        _choose(user, "transaction-instrument", "PZU")
        user.find(marker="transaction-split-ratio").type("3:1")
        user.find("Zapisz").click()

        await user.open("/transakcje")
        with user.scope(marker="transactions"):
            await user.should_see("split 3:1")
    [position] = open_positions(reversed(list_transactions(engine)))
    assert (position.quantity, position.cost) == (Decimal(30), Decimal(400))
    assert list_transactions(engine)[0].split_ratio == SplitRatio(3, 1)


@pytest.mark.parametrize("ratio", ["2-1", "2:", "1,5:1", "1:1", "0:1"])
async def test_malformed_split_ratio_is_blocked(engine: Engine, ike: int, pzu: int, ratio: str) -> None:
    _bought(engine, ike, pzu)
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")  # the Transakcje list would also offer PZU to click
        _start(user, "Split")
        _choose(user, "transaction-instrument", "PZU")
        user.find(marker="transaction-split-ratio").type(ratio)
        user.find("Zapisz").click()

        await user.should_see("X:Y")
    assert len(list_transactions(engine)) == 1


async def test_split_before_the_first_buy_is_blocked(engine: Engine, ike: int, pzu: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")  # the Transakcje list would also offer PZU to click
        _start(user, "Split")
        _choose(user, "transaction-instrument", "PZU")
        user.find(marker="transaction-split-ratio").type("2:1")
        user.find("Zapisz").click()

        await user.should_see("Split przed pierwszym zakupem")
    assert list_transactions(engine) == []


async def test_cash_transfer_moves_cash_to_the_target_account(engine: Engine, ike: int, xtb: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")  # the Transakcje list would also offer PZU to click
        _start(user, "Transfer gotówki")
        _choose(user, "transaction-target-account", "XTB")
        user.find(marker="transaction-amount").type("250")
        user.find("Zapisz").click()

        await user.open("/transakcje")
        with user.scope(marker="transactions"):
            await user.should_see("IKE → XTB")
            await user.should_see(f"250,00{NBSP}zł")
        await user.should_see("Saldo gotówki konta IKE jest ujemne")
    assert cash_balances(list_transactions(engine)) == {ike: Decimal(-250), xtb: Decimal(250)}


async def test_target_account_offers_only_the_other_accounts(engine: Engine, ike: int, xtb: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")  # the Transakcje list would also offer PZU to click
        _start(user, "Transfer gotówki", account="XTB")

        [target] = user.find(marker="transaction-target-account").elements
        assert isinstance(target, ui.select)
        assert target.options == {ike: "IKE"}


async def test_security_transfer_moves_the_units_with_their_lots(engine: Engine, ike: int, xtb: int, pzu: int) -> None:
    _bought(engine, ike, pzu)
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")  # the Transakcje list would also offer PZU to click
        _start(user, "Transfer papierów")
        _choose(user, "transaction-target-account", "XTB")
        _choose(user, "transaction-instrument", "PZU")
        user.find(marker="transaction-quantity").type("4")
        user.find("Zapisz").click()

        await user.open("/transakcje")
        with user.scope(marker="transactions"):
            await user.should_see("IKE → XTB")
            await user.should_see("4 szt.")
    moved = next(p for p in open_positions(reversed(list_transactions(engine))) if p.account_id == xtb)
    assert (moved.quantity, moved.cost, moved.lots[0].date) == (Decimal(4), Decimal(160), date(2026, 1, 2))


async def test_editing_a_security_transfer_keeps_its_target_and_quantity(
    engine: Engine, ike: int, xtb: int, pzu: int
) -> None:
    _bought(engine, ike, pzu)
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")  # the Transakcje list would also offer PZU to click
        _start(user, "Transfer papierów")
        _choose(user, "transaction-target-account", "XTB")
        _choose(user, "transaction-instrument", "PZU")
        user.find(marker="transaction-quantity").type("4")
        user.find("Zapisz").click()
        await user.open("/transakcje")
        await user.should_see("4 szt.")

        newest = min(user.find(marker="transaction-row").elements, key=lambda element: element.id)  # newest first
        UserInteraction(user, {newest}, None).click()
        await user.should_see("Edytuj transakcję")
        user.find(marker="transaction-quantity").clear().type("6")
        user.find("Zapisz zmiany").click()

        await user.should_see("6 szt.")
    transfer = list_transactions(engine)[0]
    assert (transfer.target_account_id, transfer.quantity) == (xtb, Decimal(6))
