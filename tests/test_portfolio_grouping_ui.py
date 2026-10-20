"""The Portfolio's "Grupuj" switch (issue #198): a header row per Instrument Type or Asset Class in each Account's
positions table, with the group's value and share of the Account; the choice is remembered."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft, InstrumentType
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.settings import PORTFOLIO_GROUPING, load_setting
from financial_app.persistence.transactions import add_transaction
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = init_db(tmp_path / "app.sqlite3")
    classes = {asset_class.name: asset_class.id for asset_class in list_asset_classes(engine)}
    account = add_account(engine, AccountDraft("mBank IKE", "mBank", AccountType.IKE, ("PLN",)))
    add_transaction(engine, TransactionDraft(account.id, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(4000)))
    for name, class_name, kind in (
        ("Beta ETF WIG20TR", "Akcje polskie", InstrumentType.ETF),
        ("CD Projekt", "Akcje polskie", InstrumentType.STOCK),
        ("Xtrackers MSCI World", "Akcje zagraniczne", InstrumentType.ETF),
    ):
        draft = InstrumentDraft(name, classes[class_name], "PLN", manual_price=Decimal(100), instrument_type=kind)
        instrument = add_instrument(engine, draft)
        trade = buy_or_sell(account.id, date(2026, 1, 7), TransactionType.BUY, instrument.id, Decimal(10), Decimal(100))
        add_transaction(engine, trade)
    # 3000 zł in positions and 1000 zł of cash
    return engine


async def test_without_grouping_there_are_no_group_rows(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/portfolio")

        await user.should_see(marker="position-row")
        await user.should_not_see(marker="position-group")


async def test_grouping_by_type_heads_each_group_with_its_value_and_share_and_is_remembered(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/portfolio")
        user.find(marker="portfolio-grouping").click()
        user.find("Rodzaj instrumentu").click()

        await user.should_see(marker="position-group", content="Akcja")
        await user.should_see(marker="position-group-value", content=f"2{NBSP}000,00{NBSP}zł · 50,00{NBSP}% konta")
        await user.should_see(marker="position-group-value", content=f"1{NBSP}000,00{NBSP}zł · 25,00{NBSP}% konta")
    assert load_setting(engine, PORTFOLIO_GROUPING) == "instrument_type"

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/portfolio")
        await user.should_see(marker="position-group", content="ETF")


async def test_grouping_by_asset_class(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/portfolio")
        user.find(marker="portfolio-grouping").click()
        user.find("Klasa aktywów").click()

        await user.should_see(marker="position-group", content="Akcje polskie")
        await user.should_see(marker="position-group", content="Akcje zagraniczne")
