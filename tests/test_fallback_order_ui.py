"""Each Asset Class's Fallback Order, shown and edited in Ustawienia > Klasy aktywów (issue #41), without a browser."""

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import AssetClass, InstrumentDraft
from financial_app.domain.prices import ANALIZY, BANKIER, BOSSA, YAHOO
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes, set_fallback_order
from financial_app.persistence.transactions import add_transaction
from financial_app.ui.shell import build_shell


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
async def user(engine: Engine) -> AsyncIterator[User]:
    async with user_simulation(lambda: build_shell(engine, sources={})) as user:
        await user.open("/ustawienia")
        yield user


def _class_named(engine: Engine, name: str) -> AssetClass:
    return next(c for c in list_asset_classes(engine) if c.name == name)


async def test_settings_show_each_asset_classs_fallback_order(user: User, engine: Engine) -> None:
    with user.scope(marker=f"asset-class-{_class_named(engine, 'Akcje polskie').id}"):
        await user.should_see("Bossa → Yahoo")
    with user.scope(marker=f"asset-class-{_class_named(engine, 'Gotówka').id}"):
        await user.should_see("bez źródeł")


async def test_user_removes_a_source_and_the_order_is_saved(user: User, engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje polskie")

    user.find(marker=f"edit-asset-class-{stocks.id}").click()
    user.find(marker=f"remove-source-{BOSSA}").click()
    user.find("Zapisz").click()

    assert _class_named(engine, "Akcje polskie").fallback_order == (YAHOO,)
    # The list is redrawn, so the scope is the card around it; no other class has this order
    with user.scope(marker="asset-classes"):
        await user.should_not_see("Bossa → Yahoo")


async def test_user_adds_a_source_and_moves_it_first(user: User, engine: Engine) -> None:
    bonds = _class_named(engine, "Obligacje korporacyjne polskie")

    user.find(marker=f"edit-asset-class-{bonds.id}").click()
    user.find(marker=f"add-source-{YAHOO}").click()
    # Each change redraws the editor in the background
    await user.should_see(marker=f"move-up-{YAHOO}")
    user.find(marker=f"move-up-{YAHOO}").click()
    await user.should_see("1. Yahoo")
    user.find("Zapisz").click()

    assert _class_named(engine, "Obligacje korporacyjne polskie").fallback_order == (YAHOO, BOSSA)


async def test_user_moves_a_source_down(user: User, engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje polskie")

    user.find(marker=f"edit-asset-class-{stocks.id}").click()
    user.find(marker=f"move-down-{BOSSA}").click()
    await user.should_see("1. Yahoo")
    user.find("Zapisz").click()

    assert _class_named(engine, "Akcje polskie").fallback_order == (YAHOO, BOSSA)


async def test_cancelling_keeps_the_saved_order(user: User, engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje polskie")

    user.find(marker=f"edit-asset-class-{stocks.id}").click()
    user.find(marker=f"remove-source-{BOSSA}").click()
    await user.should_not_see(marker=f"remove-source-{BOSSA}")
    user.find("Anuluj").click()

    assert _class_named(engine, "Akcje polskie").fallback_order == (BOSSA, YAHOO)


async def test_a_new_asset_class_starts_with_the_order_of_inne(user: User, engine: Engine) -> None:
    set_fallback_order(engine, _class_named(engine, "Inne").id, [BANKIER, ANALIZY])

    user.find("Dodaj klasę").click()
    with user.scope(marker="fallback-order-editor"):
        await user.should_see("bankier.pl")
    user.find(marker="asset-class-name").clear().type("Nieruchomości")
    user.find("Zapisz").click()

    assert _class_named(engine, "Nieruchomości").fallback_order == (BANKIER, ANALIZY)


async def test_removing_the_only_source_of_a_held_instrument_lists_it_without_a_price(engine: Engine) -> None:
    stocks = _class_named(engine, "Akcje polskie")
    account = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",)))
    pzu = add_instrument(engine, InstrumentDraft("PZU", stocks.id, "PLN", "GPW", source_symbols={BOSSA: "PZU"}))
    add_transaction(engine, TransactionDraft(account.id, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(1000)))
    add_transaction(
        engine, buy_or_sell(account.id, date(2026, 1, 5), TransactionType.BUY, pzu.id, Decimal(10), Decimal(40))
    )

    async with user_simulation(lambda: build_shell(engine, sources={})) as user:
        await user.open("/ustawienia")
        user.find(marker=f"edit-asset-class-{stocks.id}").click()
        user.find(marker=f"remove-source-{BOSSA}").click()
        user.find("Zapisz").click()

        with user.scope(marker="unpriced"):
            await user.should_see("PZU")
            await user.should_see("bez źródła")
