"""The export buttons on the Transakcje tab (spec 5, issue #22): each saves every Transaction as a file."""

import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from nicegui.testing import user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.transactions import TransactionDraft, TransactionType
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.transactions import add_transaction
from financial_app.sources.export import export_transactions
from financial_app.ui.shell import build_shell


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


async def test_csv_button_saves_every_transaction_with_its_comment(engine: Engine) -> None:
    ike = add_account(engine, AccountDraft("mBank IKE", "mBank", AccountType.IKE, ("PLN",))).id
    add_transaction(
        engine, TransactionDraft(ike, date(2026, 10, 5), TransactionType.DEPOSIT, Decimal("1000.50"), "start")
    )

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        user.find("Eksportuj CSV").click()
        response = await user.download.next()

    lines = response.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("Nr;Data;Konto;")
    assert lines[1].split(";")[1:4] == ["05.10.2026", "mBank IKE", ""]
    assert "start" in lines[1]


async def test_xlsx_button_saves_a_workbook_that_opens(engine: Engine) -> None:
    ike = add_account(engine, AccountDraft("mBank IKE", "mBank", AccountType.IKE, ("PLN",))).id
    add_transaction(engine, TransactionDraft(ike, date(2026, 10, 5), TransactionType.DEPOSIT, Decimal("10"), "łódź"))

    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        user.find("Eksportuj XLSX").click()
        response = await user.download.next()

    sheet = openpyxl.load_workbook(io.BytesIO(response.content)).active
    assert sheet is not None
    assert sheet["C2"].value == "mBank IKE"
    assert "łódź" in [cell.value for cell in sheet[2]]


async def test_export_with_no_transactions_saves_only_the_header(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/transakcje")
        user.find("Eksportuj CSV").click()
        response = await user.download.next()

    assert len(response.content.decode("utf-8-sig").splitlines()) == 1


def test_export_names_the_file_by_its_format(engine: Engine) -> None:
    assert export_transactions(engine, "csv")[0] == "transakcje.csv"
    assert export_transactions(engine, "xlsx")[0] == "transakcje.xlsx"
