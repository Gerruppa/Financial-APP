"""Ustawienia > Import z arkusza (issue #20): preview first, then save, on a synthetic workbook, without a browser."""

from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.spreadsheet_import import COLUMNS
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.transactions import list_transactions
from financial_app.sources.nbp import NbpRates
from financial_app.ui.reset import CONFIRMATION_PHRASE
from financial_app.ui.shell import build_shell

USD = NbpRate("USD", Decimal("3.6500"), date(2026, 4, 23), "086/A/NBP/2026")


class FixedNbp(NbpRates):
    """NBP Rates from a fixed table, so the test needs no network."""

    def __init__(self, engine: Engine) -> None:
        super().__init__(engine, fetch=lambda url: None, today=lambda: date(2026, 10, 9))

    def before(self, currency: str, day: date) -> NbpRate:
        assert currency == "USD"
        return USD


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def workbook(tmp_path: Path) -> Path:
    path = tmp_path / "synthetic.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "Transakcje"
    # The sheet also has a "Cena nominalna" column the import does not read
    sheet.append([*COLUMNS.values()][:11] + ["Cena nominalna"] + [*COLUMNS.values()][11:])
    sheet.append(
        [
            "IKE",
            datetime(2026, 4, 24),
            "LON:ISAC",
            "USD",
            "iShares MSCI ACWI",
            "Akcje zagraniczne",
            "Zakup",
            0.3479,
            114.72,
            0.0,
            3.6503,
            1.0,
            145.68,
            "IKE MSCI ACWI",
        ]
    )
    book.save(path)
    return path


@pytest.fixture
async def user(engine: Engine, workbook: Path) -> AsyncIterator[User]:
    async with user_simulation(lambda: build_shell(engine, FixedNbp(engine))) as user:
        await user.open("/ustawienia")
        yield user


async def test_preview_saves_nothing_and_save_imports_the_rows(engine: Engine, workbook: Path, user: User) -> None:
    add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN", "USD")))

    user.find(marker="import-path").type(str(workbook))
    user.find(marker="import-preview").click()

    assert list_transactions(engine) == []
    user.find(marker="import-save").click()
    assert len(list_transactions(engine)) == 1
    assert [transaction.comment for transaction in list_transactions(engine)] == ["IKE MSCI ACWI"]


async def test_an_imported_transaction_is_marked_as_imported_in_the_list(engine: Engine, workbook: Path) -> None:
    add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN", "USD")))
    async with user_simulation(lambda: build_shell(engine, FixedNbp(engine))) as user:
        await user.open("/ustawienia")
        user.find(marker="import-path").type(str(workbook))
        user.find(marker="import-preview").click()
        user.find(marker="import-save").click()

        await user.open("/transakcje")

        user.find(marker="transaction-origin")


async def test_clearing_the_data_drops_an_open_preview(engine: Engine, workbook: Path, user: User) -> None:
    """The preview's choices name Accounts and Instruments that clearing removes, so it must not stay savable."""
    add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN", "USD")))
    user.find(marker="import-path").type(str(workbook))
    user.find(marker="import-preview").click()
    await user.should_see(marker="import-save")

    user.find(marker="clear-data").click()
    user.find(marker="clear-data-next").click()
    # The browser deletes the hidden warning; the simulation does not, so do it here
    for dialog in user.find(ui.dialog).elements:
        if isinstance(dialog, ui.dialog) and not dialog.value:
            dialog.delete()
    user.find(marker="clear-data-phrase").type(CONFIRMATION_PHRASE)
    user.find(marker="clear-data-confirm").click()

    await user.should_see("Wyczyszczono dane")
    await user.should_not_see(marker="import-save")
