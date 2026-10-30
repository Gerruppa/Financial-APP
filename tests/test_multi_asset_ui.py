"""Multi-asset Splits in the window (issue #75): the split in the Instrument dialog, the split dialog after buying an
Instrument without one, and the Multi-asset tab."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.spreadsheet_import import COLUMNS
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import (
    add_instrument,
    list_asset_classes,
    list_instruments,
    rename_asset_class,
)
from financial_app.persistence.transactions import add_transactions
from financial_app.ui import settings
from financial_app.ui.shell import build_shell

NBSP = "\xa0"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _class_id(engine: Engine, name: str) -> int:
    return next(c.id for c in list_asset_classes(engine) if c.name == name)


def _vanguard(engine: Engine, split: dict[int, Decimal] | None = None) -> int:
    draft = InstrumentDraft(
        "Vanguard LifeStrategy 80",
        _class_id(engine, "Multi-asset"),
        "PLN",
        manual_price=Decimal(60),
        multi_asset_split=split or {},
    )
    return add_instrument(engine, draft).id


def _eighty_twenty(engine: Engine) -> dict[int, Decimal]:
    return {
        _class_id(engine, "Akcje zagraniczne"): Decimal(80),
        _class_id(engine, "Obligacje skarbowe zagraniczne"): Decimal(20),
    }


def _type_split(user: User, engine: Engine, stocks: str, bonds: str) -> None:
    user.find(marker=f"split-share-{_class_id(engine, 'Akcje zagraniczne')}").clear().type(stocks)
    user.find(marker=f"split-share-{_class_id(engine, 'Obligacje skarbowe zagraniczne')}").clear().type(bonds)


def _choose_asset_class(user: User, name: str) -> None:
    with user.scope(marker="instrument-dialog"):
        user.find(marker="instrument-class").click()
        user.find(name).click()


async def test_a_multi_asset_instrument_gets_its_split_in_the_instrument_dialog(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find("Dodaj instrument").click()
        await user.should_not_see(marker="multi-asset-split")
        user.find(marker="instrument-name").type("Vanguard LifeStrategy 80")
        _choose_asset_class(user, "Multi-asset")
        await user.should_see(marker="multi-asset-split")
        _type_split(user, engine, "80", "20")
        await user.should_see("Razem: 100,00 %")
        user.find("Zapisz").click()

        with user.scope(marker="instruments"):
            await user.should_see("Vanguard LifeStrategy 80")

    [saved] = list_instruments(engine)
    assert saved.multi_asset_split == _eighty_twenty(engine)


async def test_a_split_not_summing_to_100_is_not_saved(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find("Dodaj instrument").click()
        user.find(marker="instrument-name").type("Vanguard LifeStrategy 80")
        _choose_asset_class(user, "Multi-asset")
        _type_split(user, engine, "70", "20,5")
        await user.should_see("Razem: 90,50 %")
        user.find("Zapisz").click()

        await user.should_see("teraz 90,50 %")
    assert list_instruments(engine) == []


async def test_an_instrument_moved_out_of_multi_asset_loses_its_split(engine: Engine) -> None:
    _vanguard(engine, _eighty_twenty(engine))

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-instrument").click()
        _choose_asset_class(user, "Inne")
        await user.should_not_see(marker="multi-asset-split")
        user.find("Zapisz").click()
        await user.should_not_see(marker="instrument-dialog")

    [saved] = list_instruments(engine)
    assert saved.multi_asset_split == {}


async def test_a_renamed_multi_asset_class_still_offers_the_split_and_keeps_it(engine: Engine) -> None:
    _vanguard(engine, _eighty_twenty(engine))
    rename_asset_class(engine, _class_id(engine, "Multi-asset"), "Fundusze mieszane")

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-instrument").click()
        await user.should_see(marker="multi-asset-split")
        user.find(marker="instrument-price").clear().type("61")
        user.find("Zapisz").click()

        with user.scope(marker="instruments"):
            await user.should_see("61,00 PLN")
    [saved] = list_instruments(engine)
    assert saved.multi_asset_split == _eighty_twenty(engine)


async def test_buying_a_multi_asset_instrument_without_a_split_asks_for_it(engine: Engine) -> None:
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    _vanguard(engine)
    add_transactions(engine, [TransactionDraft(ike, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(1000))])

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="add-transaction").click()
        user.find(marker="transaction-type").click()
        user.find("Zakup").click()
        user.find(marker="transaction-instrument").click()
        user.find("Vanguard LifeStrategy 80").click()
        user.find(marker="transaction-quantity").type("10")
        user.find(marker="transaction-price").type("50")
        user.find("Zapisz").click()

        await user.should_see(marker="split-dialog")
        _type_split(user, engine, "80", "20")
        user.find(marker="save-split").click()

    [saved] = list_instruments(engine)
    assert saved.multi_asset_split == _eighty_twenty(engine)


async def test_editing_a_buy_of_a_multi_asset_instrument_without_a_split_asks_for_it(engine: Engine) -> None:
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    vanguard = _vanguard(engine)
    add_transactions(
        engine, [buy_or_sell(ike, date(2026, 1, 2), TransactionType.BUY, vanguard, Decimal(10), Decimal(50))]
    )

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()
        user.find(marker="transaction-quantity").clear().type("4")
        user.find("Zapisz zmiany").click()

        await user.should_see(marker="split-dialog")


async def test_an_import_with_an_unsplit_multi_asset_instrument_points_to_the_multi_asset_tab(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "SHOW_SHEET_IMPORT", True)  # hidden in Ustawienia (#269)
    add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",)))
    workbook = tmp_path / "sheet.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "Transakcje"
    sheet.append([*COLUMNS.values()][:11] + ["Cena nominalna"] + [*COLUMNS.values()][11:])
    row = ["IKE", datetime(2026, 4, 24), "WSE:V80A", "PLN", "Vanguard LifeStrategy 80", "Multi-asset", "Zakup"]
    sheet.append([*row, 2.0, 100.0, 0.0, 1.0, 1.0, 200.0, ""])
    book.save(workbook)

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="import-path").type(str(workbook))
        user.find(marker="import-preview").click()
        user.find(marker="import-save").click()

        await user.should_see("Zaimportowano transakcje: 1.")
        await user.should_see("Instrumenty Multi-asset bez podziału na klasy: V80A")


async def test_the_multi_asset_tab_shows_each_instrument_with_its_value_per_class(engine: Engine) -> None:
    ike = add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",))).id
    vanguard = _vanguard(engine, _eighty_twenty(engine))
    unsplit = add_instrument(
        engine, InstrumentDraft("PPK 2060", _class_id(engine, "Multi-asset"), "PLN", manual_price=Decimal(10))
    ).id
    add_transactions(
        engine,
        [
            TransactionDraft(ike, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(1000)),
            buy_or_sell(ike, date(2026, 1, 2), TransactionType.BUY, vanguard, Decimal(10), Decimal(50)),
            buy_or_sell(ike, date(2026, 1, 2), TransactionType.BUY, unsplit, Decimal(5), Decimal(10)),
        ],
    )

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/multi-asset")

        with user.scope(marker="multi-asset"):
            await user.should_see("Vanguard LifeStrategy 80")
            await user.should_see(f"Akcje zagraniczne 80,00{NBSP}%: 480,00{NBSP}zł")
            await user.should_see(marker="multi-asset-no-split")
        assert len(user.find(marker="multi-asset-class").elements) == 3

        user.find(marker=f"multi-asset-row-{unsplit}").click()
        await user.should_see(marker="split-dialog")
        user.find(marker=f"split-share-{_class_id(engine, 'Inne')}").type("100")
        user.find(marker="save-split").click()

        await user.should_not_see(marker="multi-asset-no-split")
