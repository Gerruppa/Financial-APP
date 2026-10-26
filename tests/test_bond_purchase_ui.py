"""Buying retail treasury bonds in the "+" dialog's bond mode (L-2, spec 3.4.1): the type and the purchase date give
the Bond Series, created on its first purchase, at 100 zł or, "z rolowania", at the MF Rollover price."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.bonds import SeriesTerms
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.transactions import TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.bond_data import save_series_terms
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, get_instrument, list_asset_classes, list_instruments
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.ui.shell import build_shell

NBSP = "\xa0"


def _terms(series: str, rate: str, rollover: str | None = "99.9") -> SeriesTerms:
    return SeriesTerms(
        series,
        "PL0000119566",
        date(2026, 10, 1),
        date(2026, 10, 31),
        Decimal(100),
        None if rollover is None else Decimal(rollover),
        Decimal("0.02"),
        (Decimal(rate), None),
        (None,),
    )


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = init_db(tmp_path / "app.sqlite3")
    save_series_terms(engine, [_terms("EDO1036", "0.0535"), _terms("ROS1032", "0.05", rollover=None)])
    return engine


@pytest.fixture
def bonds(engine: Engine) -> int:
    return add_account(engine, AccountDraft("PKO Obligacje", "PKO BP", AccountType.BONDS, ("PLN",))).id


def _open_bond_purchase(user: User, day: str = "12.10.2026") -> None:
    user.find(marker="add-transaction").click()
    user.find(marker="transaction-type").click()
    user.find("Zakup").click()
    user.find(marker="transaction-date").clear().type(day)


async def test_a_purchase_on_a_bonds_account_creates_the_series_of_the_type_and_month(
    engine: Engine, bonds: int
) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        _open_bond_purchase(user)

        await user.should_see("Seria EDO1036")
        await user.should_see(f"1. okres: 5,35{NBSP}%")
        user.find(marker="transaction-quantity").type("10")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see("EDO1036")
            await user.should_see(f"-1{NBSP}000,00{NBSP}zł")
    [purchase] = list_transactions(engine)
    assert purchase.instrument_id is not None
    edo = get_instrument(engine, purchase.instrument_id)
    assert (edo.name, edo.isin, edo.is_bond_series) == ("EDO1036", "PL0000119566", True)
    assert (purchase.transaction_type, purchase.quantity, purchase.price, purchase.commission) == (
        TransactionType.BUY,
        Decimal(10),
        Decimal(100),
        Decimal(0),
    )


async def test_the_type_and_date_choose_the_series_even_one_the_mf_file_does_not_list_yet(
    engine: Engine, bonds: int
) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        _open_bond_purchase(user, day="03.11.2026")
        user.find(marker="transaction-bond-type").click()
        user.find("COI · 4 lata").click()

        await user.should_see("Seria COI1130")
        await user.should_see("jeszcze nie ma jej w pliku MF")
        user.find(marker="transaction-quantity").type("5")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see("COI1130")
    assert [i.name for i in list_instruments(engine)] == ["COI1130"]


async def test_a_rollover_purchase_is_at_the_mf_rollover_price(engine: Engine, bonds: int) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        _open_bond_purchase(user)
        user.find(marker="transaction-rollover").click()
        user.find(marker="transaction-quantity").type("10")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see(f"-999,00{NBSP}zł")
    [purchase] = list_transactions(engine)
    assert purchase.price == Decimal("99.9")


async def test_family_bonds_offer_no_rollover(engine: Engine, bonds: int) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        _open_bond_purchase(user)
        user.find(marker="transaction-bond-type").click()
        user.find("ROS · 6 lat").click()

        await user.should_see("Seria ROS1032")
        await user.should_not_see(marker="transaction-rollover")


async def test_a_second_purchase_in_the_month_adds_to_the_same_series(engine: Engine, bonds: int) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        for day in ("05.10.2026", "28.10.2026"):
            _open_bond_purchase(user, day=day)
            user.find(marker="transaction-quantity").type("3")
            user.find("Zapisz").click()
            with user.scope(marker="transactions"):
                await user.should_see(day)

    assert [i.name for i in list_instruments(engine)] == ["EDO1036"]
    assert len({t.instrument_id for t in list_transactions(engine)}) == 1


async def test_other_accounts_buy_instruments_until_the_bond_mode_is_chosen(engine: Engine) -> None:
    add_account(engine, AccountDraft("mBank IKE", "mBank", AccountType.IKE, ("PLN",)))
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        _open_bond_purchase(user)

        await user.should_see(marker="transaction-instrument")
        await user.should_not_see("Seria EDO1036")
        user.find(marker="transaction-bond-mode").click()

        await user.should_see("Seria EDO1036")
        await user.should_not_see(marker="transaction-instrument")


async def test_the_bond_mode_on_a_regular_account_hints_at_a_bonds_account(engine: Engine) -> None:
    add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",)))
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        _open_bond_purchase(user)

        await user.should_not_see(marker="transaction-bond-hint")
        user.find(marker="transaction-bond-mode").click()

        await user.should_see(marker="transaction-bond-hint")
        await user.should_see("nie przyjmuje obligacji skarbowych detalicznych")


async def test_a_bonds_account_shows_no_hint(engine: Engine, bonds: int) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        _open_bond_purchase(user)

        await user.should_see("Seria EDO1036")
        await user.should_not_see(marker="transaction-bond-hint")


async def test_a_bond_purchase_opens_in_the_bond_mode_for_editing(engine: Engine, bonds: int) -> None:
    treasury = next(c for c in list_asset_classes(engine) if c.name == "Obligacje skarbowe polskie")
    edo = add_instrument(engine, InstrumentDraft("EDO0836", treasury.id, "PLN")).id
    add_transaction(
        engine,
        buy_or_sell(bonds, date(2026, 8, 4), TransactionType.BUY, edo, Decimal(20), Decimal("99.9"), Decimal(0)),
    )
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()

        await user.should_see("Seria EDO0836")
        [price] = user.find(marker="transaction-price").elements
        assert isinstance(price, ui.input) and price.value == "99,90"
        user.find(marker="transaction-quantity").clear().type("25")
        user.find("Zapisz zmiany").click()

        with user.scope(marker="transactions"):
            await user.should_see("25 × 99,90")
    [purchase] = list_transactions(engine)
    assert (purchase.instrument_id, purchase.quantity, purchase.price) == (edo, Decimal(25), Decimal("99.9"))


def _edo0836_bought(engine: Engine, bonds: int, day: date, commission: str = "0") -> int:
    treasury = next(c for c in list_asset_classes(engine) if c.name == "Obligacje skarbowe polskie")
    edo = add_instrument(engine, InstrumentDraft("EDO0836", treasury.id, "PLN")).id
    purchase = buy_or_sell(bonds, day, TransactionType.BUY, edo, Decimal(20), Decimal(100), Decimal(commission))
    add_transaction(engine, purchase)
    return edo


async def test_an_edited_purchase_keeps_its_series_even_dated_in_another_month(engine: Engine, bonds: int) -> None:
    # Imported with the settlement day, which falls in the next month
    edo = _edo0836_bought(engine, bonds, date(2026, 9, 1), commission="5")
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()

        await user.should_see("Seria EDO0836")
        user.find(marker="transaction-comment").type("rozliczenie")
        user.find("Zapisz zmiany").click()

        with user.scope(marker="transactions"):
            await user.should_see("rozliczenie")
    [purchase] = list_transactions(engine)
    assert (purchase.instrument_id, purchase.commission) == (edo, Decimal(5))
    assert [i.name for i in list_instruments(engine)] == ["EDO0836"]


async def test_moving_a_purchase_to_another_month_moves_it_to_that_series(engine: Engine, bonds: int) -> None:
    _edo0836_bought(engine, bonds, date(2026, 8, 4))
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()
        user.find(marker="transaction-date").clear().type("12.10.2026")

        await user.should_see("Seria EDO1036")
        user.find("Zapisz zmiany").click()

        with user.scope(marker="transactions"):
            await user.should_see("EDO1036")
    # The Series the Purchase left holds nothing else, so it goes
    assert [i.name for i in list_instruments(engine)] == ["EDO1036"]


async def test_a_typed_price_survives_a_change_of_the_date(engine: Engine, bonds: int) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        _open_bond_purchase(user)
        user.find(marker="transaction-price").clear().type("99,8")
        user.find(marker="transaction-date").clear().type("13.10.2026")

        [price] = user.find(marker="transaction-price").elements
        assert isinstance(price, ui.input) and price.value == "99,8"


async def test_an_instrument_of_another_class_with_the_series_name_is_not_bought_as_bonds(
    engine: Engine, bonds: int
) -> None:
    corporate = next(c for c in list_asset_classes(engine) if c.name == "Obligacje korporacyjne polskie")
    add_instrument(engine, InstrumentDraft("EDO1036", corporate.id, "PLN"))
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        _open_bond_purchase(user)
        user.find(marker="transaction-quantity").type("10")
        user.find("Zapisz").click()

        await user.should_see("nie jest serią obligacji skarbowych")
    assert list_transactions(engine) == []


def _past_terms(series: str, first: date, last: date) -> SeriesTerms:
    return SeriesTerms(
        series, "PL0000110151", first, last, Decimal(100), Decimal("99.9"), Decimal("0.0075"), (Decimal("0.027"),), ()
    )


async def test_an_older_purchase_picks_its_series_from_the_mf_list(engine: Engine, bonds: int) -> None:
    save_series_terms(engine, [_past_terms("EDO0827", date(2017, 8, 1), date(2017, 8, 31))])
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        _open_bond_purchase(user, day="14.08.2017")

        # The type and date give the Series by themselves
        await user.should_see("Seria EDO0827")
        user.find(marker="transaction-date").clear().type("12.10.2026")
        await user.should_see("Seria EDO1036")
        user.find(marker="transaction-bond-series-choice").click()
        user.find("EDO0827 · sprzedaż 08.2017").click()

        await user.should_see("Seria EDO0827")
        await user.should_see("data zakupu poza sprzedażą serii (01.08.2017–31.08.2017)")
        user.find(marker="transaction-date").clear().type("14.08.2017")
        await user.should_not_see("poza sprzedażą serii")
        user.find(marker="transaction-quantity").type("10")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see("EDO0827")
    [purchase] = list_transactions(engine)
    assert purchase.instrument_id is not None
    edo = get_instrument(engine, purchase.instrument_id)
    assert (edo.name, edo.isin, purchase.price) == ("EDO0827", "PL0000110151", Decimal(100))


async def test_a_rollover_may_be_dated_a_few_days_after_the_sale(engine: Engine, bonds: int) -> None:
    save_series_terms(engine, [_past_terms("EDO0827", date(2017, 8, 1), date(2017, 8, 31))])
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        _open_bond_purchase(user, day="04.09.2017")
        user.find(marker="transaction-bond-series-choice").click()
        user.find("EDO0827 · sprzedaż 08.2017").click()

        await user.should_see("poza sprzedażą serii")
        user.find(marker="transaction-rollover").click()

        await user.should_not_see("poza sprzedażą serii")
        [price] = user.find(marker="transaction-price").elements
        assert isinstance(price, ui.input) and price.value == "99,90"


async def test_another_type_drops_the_picked_series(engine: Engine, bonds: int) -> None:
    save_series_terms(engine, [_past_terms("EDO0827", date(2017, 8, 1), date(2017, 8, 31))])
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        _open_bond_purchase(user)
        user.find(marker="transaction-bond-series-choice").click()
        user.find("EDO0827 · sprzedaż 08.2017").click()
        await user.should_see("Seria EDO0827")
        user.find(marker="transaction-bond-type").click()
        user.find("ROS · 6 lat").click()

        await user.should_see("Seria ROS1032")
