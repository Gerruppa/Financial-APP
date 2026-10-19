"""Early Redemption in the "+" dialog (L-5, spec 3.4.1, ADR-0007): a Sell of a Bond Series picks its Lot (the oldest
by default) and is prefilled with the gross value of one bond, the early-redemption fee and the tax withheld."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, UserInteraction, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.bonds import SeriesTerms
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.transactions import Transaction, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.bond_data import save_series_terms
from financial_app.persistence.bond_series import series_instrument
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.ui.shell import build_shell

NBSP = "\xa0"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = init_db(tmp_path / "app.sqlite3")
    rates = (Decimal("0.065"), Decimal("0.0535")) + (None,) * 8
    terms = SeriesTerms(
        "EDO0534",
        "PL0000116281",
        date(2024, 5, 1),
        date(2024, 5, 31),
        Decimal(100),
        Decimal("99.9"),
        Decimal("0.02"),
        rates,
        (None,),
    )
    save_series_terms(engine, [terms])
    return engine


@pytest.fixture
def bonds(engine: Engine) -> int:
    return add_account(engine, AccountDraft("PKO Obligacje", "PKO BP", AccountType.BONDS, ("PLN",))).id


def _bought(engine: Engine, account: int, day: date, quantity: int = 10) -> Transaction:
    edo, _ = series_instrument(engine, "EDO0534")
    purchase = buy_or_sell(account, day, TransactionType.BUY, edo.id, Decimal(quantity), Decimal(100))
    return add_transaction(engine, purchase)


def _value(user: User, marker: str) -> object:
    [element] = user.find(marker=marker).elements
    assert isinstance(element, ui.input | ui.select)
    return element.value


def _choose(user: User, marker: str, value: object) -> None:
    [element] = user.find(marker=marker).elements
    assert isinstance(element, ui.select)
    element.value = value


def _open_redemption(user: User, engine: Engine, account: int, day: str = "08.10.2025") -> None:
    user.find(marker="add-transaction").click()
    _choose(user, "transaction-type", TransactionType.SELL.value)
    _choose(user, "transaction-account", account)
    edo, _ = series_instrument(engine, "EDO0534")
    _choose(user, "transaction-instrument", edo.id)
    user.find(marker="transaction-date").clear().type(day)


async def test_a_redemption_picks_the_oldest_lot_and_is_prefilled(engine: Engine, bonds: int) -> None:
    oldest = _bought(engine, bonds, date(2024, 5, 22))
    _bought(engine, bonds, date(2025, 3, 3), quantity=5)
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/benchmarki")
        _open_redemption(user, engine, bonds)

        await user.should_see(marker="transaction-lot")
        assert _value(user, "transaction-lot") == oldest.id
        user.find(marker="transaction-quantity").clear().type("4")

        # One bond: 108.67 zł, the 2 zł fee of a pre-September 2024 issue and 1.27 zł Belka, times 4 bonds
        assert _value(user, "transaction-price") == "108,67"
        assert _value(user, "transaction-commission") == "8,00"
        assert _value(user, "transaction-withholding-tax") == "5,08"
        await user.should_see(f"Wypłata netto: 421,60{NBSP}zł")
        user.find("Zapisz").click()

    redemption = next(t for t in list_transactions(engine) if t.transaction_type is TransactionType.SELL)
    assert (redemption.lot_id, redemption.quantity, redemption.actual_amount) == (
        oldest.id,
        Decimal(4),
        Decimal("421.60"),
    )
    assert (redemption.commission, redemption.withholding_tax) == (Decimal("8.00"), Decimal("5.08"))


async def test_choosing_another_lot_fills_its_quantity_and_values(engine: Engine, bonds: int) -> None:
    _bought(engine, bonds, date(2024, 5, 22))
    newer = _bought(engine, bonds, date(2025, 3, 3), quantity=5)
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/benchmarki")
        _open_redemption(user, engine, bonds)
        _choose(user, "transaction-lot", newer.id)

        # 219 days at 6.5%: 103.90 zł, the fee takes 2 zł, 19% of 1.90 zł is 0.36 zł
        assert _value(user, "transaction-quantity") == "5"
        assert _value(user, "transaction-price") == "103,90"
        assert _value(user, "transaction-commission") == "10,00"
        assert _value(user, "transaction-withholding-tax") == "1,80"
        await user.should_see(f"Wypłata netto: 507,70{NBSP}zł")
        user.find("Zapisz").click()

    redemption = next(t for t in list_transactions(engine) if t.transaction_type is TransactionType.SELL)
    assert redemption.lot_id == newer.id


async def test_typed_values_stay_when_the_quantity_changes(engine: Engine, bonds: int) -> None:
    _bought(engine, bonds, date(2024, 5, 22))
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/benchmarki")
        _open_redemption(user, engine, bonds)
        user.find(marker="transaction-commission").clear().type("7,50")
        user.find(marker="transaction-quantity").clear().type("3")

        assert _value(user, "transaction-commission") == "7,50"
        assert _value(user, "transaction-withholding-tax") == "3,81"


async def test_an_edited_redemption_keeps_its_lot_and_amounts(engine: Engine, bonds: int) -> None:
    _bought(engine, bonds, date(2024, 5, 22))
    newer = _bought(engine, bonds, date(2025, 3, 3), quantity=5)
    edo, _ = series_instrument(engine, "EDO0534")
    redemption = buy_or_sell(
        bonds,
        date(2025, 10, 8),
        TransactionType.SELL,
        edo.id,
        Decimal(5),
        Decimal("103.9"),
        Decimal(10),
        withholding_tax=Decimal("1.75"),
        lot_id=newer.id,
    )
    saved = add_transaction(engine, redemption)
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        newest = min(user.find(marker="transaction-row").elements, key=lambda element: element.id)
        UserInteraction(user, {newest}, None).click()
        await user.should_see("Edytuj transakcję")

        assert _value(user, "transaction-lot") == newer.id
        assert _value(user, "transaction-withholding-tax") == "1,75"
        user.find(marker="transaction-comment").type("wg wyciągu")
        user.find("Zapisz zmiany").click()
        await user.should_see("wg wyciągu")

    [edited] = [t for t in list_transactions(engine) if t.id == saved.id]
    assert (edited.lot_id, edited.withholding_tax, edited.actual_amount) == (
        newer.id,
        Decimal("1.75"),
        Decimal("507.75"),
    )


async def test_an_ike_withholds_no_tax(engine: Engine) -> None:
    ike = add_account(engine, AccountDraft("PKO IKE", "PKO BP", AccountType.IKE, ("PLN",))).id
    _bought(engine, ike, date(2024, 5, 22))
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/benchmarki")
        _open_redemption(user, engine, ike)
        user.find(marker="transaction-quantity").clear().type("1")

        assert _value(user, "transaction-commission") == "2,00"
        assert _value(user, "transaction-withholding-tax") == "0,00"


async def test_a_sell_of_another_instrument_picks_no_lot(engine: Engine, bonds: int) -> None:
    shares = next(c for c in list_asset_classes(engine) if c.name == "Akcje polskie")
    pzu = add_instrument(engine, InstrumentDraft("PZU", shares.id, "PLN")).id
    add_transaction(engine, buy_or_sell(bonds, date(2025, 1, 2), TransactionType.BUY, pzu, Decimal(5), Decimal(40)))
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/benchmarki")
        user.find(marker="add-transaction").click()
        _choose(user, "transaction-type", TransactionType.SELL.value)
        _choose(user, "transaction-instrument", pzu)

        await user.should_not_see(marker="transaction-lot")
        await user.should_not_see(marker="transaction-withholding-tax")
