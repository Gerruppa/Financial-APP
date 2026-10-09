"""Writing the Transakcje list to CSV and XLSX files (spec 5, issue #22), so the data never stays inside the app.

CSV follows Polish Excel: UTF-8 with a byte-order mark so the Polish letters show, ';' between fields, a decimal
comma and day-first dates. XLSX keeps numbers and dates as Excel cells.
"""

import csv
import io
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Literal

import openpyxl
from sqlalchemy import Engine

from financial_app.domain.export import COLUMNS, export_rows
from financial_app.domain.formatting import format_date
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import list_transactions

FileFormat = Literal["csv", "xlsx"]
XLSX_DATE_FORMAT = "DD.MM.YYYY"
# Text starting with one of these would run as a formula when a spreadsheet opens it, so it is kept as text
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
BYTE_ORDER_MARK = "\ufeff"


def _csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return format_date(value)
    if isinstance(value, Decimal):
        return format(value, "f").replace(".", ",")
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value  # the apostrophe makes Excel show it as text
    return str(value)


def to_csv(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> bytes:
    text = io.StringIO()
    writer = csv.writer(text, delimiter=";", lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_csv_cell(value) for value in row])
    return (BYTE_ORDER_MARK + text.getvalue()).encode("utf-8")


def to_xlsx(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Transakcje"
    sheet.append(list(headers))
    date_column = list(headers).index("Data") + 1
    for row in rows:
        sheet.append(list(row))
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str) and cell.value.startswith(FORMULA_START):
                cell.data_type = "s"  # stays text, not a formula
    for row_number in range(2, sheet.max_row + 1):
        sheet.cell(row_number, date_column).number_format = XLSX_DATE_FORMAT
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def export_transactions(engine: Engine, file_format: FileFormat) -> tuple[str, bytes]:
    """The file name and the bytes of every saved Transaction, in the order the Transakcje list shows them."""
    transactions = list_transactions(engine)
    accounts = {account.id: account.name for account in list_accounts(engine)}
    instruments = {instrument.id: instrument for instrument in list_instruments(engine)}
    rows = export_rows(transactions, accounts, instruments)
    if file_format == "csv":
        return "transakcje.csv", to_csv(COLUMNS, rows)
    return "transakcje.xlsx", to_xlsx(COLUMNS, rows)
