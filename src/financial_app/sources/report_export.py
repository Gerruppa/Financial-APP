"""Writing a report to an XLSX file (issue #240, parent #239), so the Sell Summary and Wyniki leave the app as data.

``report_to_xlsx`` turns a ``domain/report.py`` ``Report`` into a workbook, a sheet per section: amounts and
quantities are numbers, percents are fractions shown as percent, dates are real dates shown day-first. The report
functions build the model for a year and a View Scope from the database and name the file after the report, the year
and, for one Account, the Account.
"""

import io
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

import openpyxl
from openpyxl.cell import Cell as SheetCell
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy import Engine

from financial_app.domain.lots import foreign_cash, open_positions
from financial_app.domain.portfolio_history import DayValue, prices_on, rates_on
from financial_app.domain.report import (
    ALL_ACCOUNTS,
    Cell,
    Percent,
    PortfolioSnapshot,
    Report,
    Section,
    passive_income_report,
    portfolio_report,
    results_report,
    sale_summary_report,
)
from financial_app.domain.transactions import cash_balances
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.bond_data import load_cpi
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import transactions_in_entry_order
from financial_app.sources.current_prices import LatestRates
from financial_app.sources.export import FORMULA_START, XLSX_DATE_FORMAT, safe_file_part
from financial_app.sources.passive_income import income_items
from financial_app.sources.pdf_report import annual_report_to_pdf
from financial_app.sources.portfolio_history import history_inputs
from financial_app.sources.todays_view import todays_view

XLSX_NUMBER_FORMAT = "#,##0.00##"
XLSX_PERCENT_FORMAT = "0.00%"
# A sheet's name holds at most 31 characters and none of these
_SHEET_NAME_LENGTH = 31
_SHEET_NAME_UNSAFE = str.maketrans("", "", "[]:*?/\\")


def report_to_xlsx(report: Report) -> bytes:
    workbook = openpyxl.Workbook()
    first = workbook.active
    assert first is not None
    workbook.properties.title = report.title
    if not report.sections:
        first.title = _sheet_name(report.title)
        for note in report.notes:
            first.append([note])
    for index, section in enumerate(report.sections):
        sheet = first if index == 0 else workbook.create_sheet()
        _write_section(sheet, section)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _write_section(sheet: Worksheet, section: Section) -> None:
    sheet.title = _sheet_name(section.title)
    sheet.append(list(section.headers))
    for row_number, row in enumerate(section.rows, start=2):
        for column, source in enumerate(row, start=1):
            _format(sheet.cell(row_number, column, _value(source)), source)
    if section.notes:
        sheet.append([])
        for note in section.notes:
            sheet.append([note])


def _value(cell: Cell) -> str | int | Decimal | date | None:
    return cell.fraction if isinstance(cell, Percent) else cell


def _format(cell: SheetCell, source: Cell) -> None:
    if isinstance(source, str) and source.startswith(FORMULA_START):
        cell.data_type = "s"  # stays text, not a formula
    elif isinstance(source, Percent):
        cell.number_format = XLSX_PERCENT_FORMAT
    elif isinstance(source, date):
        cell.number_format = XLSX_DATE_FORMAT
    elif isinstance(source, Decimal):
        cell.number_format = XLSX_NUMBER_FORMAT


def _sheet_name(title: str) -> str:
    return title.translate(_SHEET_NAME_UNSAFE)[:_SHEET_NAME_LENGTH]


def export_sale_summary(engine: Engine, year: int, account_id: int | None) -> tuple[str, bytes]:
    """The file name and bytes of the Sell Summary of ``year`` for the View Scope (``account_id``, ``None``: Total)."""
    report = _sale_summary(engine, year, account_id)
    return _named(report, year, account_id, _account_names(engine)), report_to_xlsx(report)


def export_results(
    engine: Engine, year: int, account_id: int | None, history: Sequence[DayValue], today: date
) -> tuple[str, bytes]:
    """The file name and bytes of Wyniki over ``year`` for the View Scope, from ``history``'s days."""
    report = _results(engine, year, account_id, history, today)
    return _named(report, year, account_id, _account_names(engine)), report_to_xlsx(report)


def export_portfolio(engine: Engine, year: int, account_id: int | None, rates: LatestRates) -> tuple[str, bytes]:
    """The file name and bytes of the Portfolio at the end of ``year`` for the View Scope: as the Portfolio tab shows
    it for the current year (at today's prices), else as History values it on 31 December from the cached prices."""
    report = _portfolio(engine, year, account_id, rates)
    return _named(report, year, account_id, _account_names(engine)), report_to_xlsx(report)


def export_passive_income(engine: Engine, year: int, account_id: int | None, today: date) -> tuple[str, bytes]:
    """The file name and bytes of the passive income received in ``year`` for the View Scope."""
    report = _passive_income(engine, year, account_id, today)
    return _named(report, year, account_id, _account_names(engine)), report_to_xlsx(report)


def export_annual_pdf(
    engine: Engine, year: int, account_id: int | None, history: Sequence[DayValue], rates: LatestRates
) -> tuple[str, bytes]:
    """The file name and bytes of the annual PDF report of ``year`` for the View Scope: the four reports the XLSX files
    hold (Wyniki, Portfolio, Sell Summary, passive income), built the same way so the figures agree."""
    today = rates.today()
    names = _account_names(engine)
    reports = (
        _results(engine, year, account_id, history, today),
        _portfolio(engine, year, account_id, rates),
        _sale_summary(engine, year, account_id),
        _passive_income(engine, year, account_id, today),
    )
    scope = ALL_ACCOUNTS if account_id is None else names[account_id]
    name = _file_name("raport-roczny", year, account_id, names, "pdf")
    return name, annual_report_to_pdf(scope, year, today, reports)


def _account_names(engine: Engine) -> dict[int, str]:
    return {account.id: account.name for account in list_accounts(engine)}


def _instrument_names(engine: Engine) -> dict[int, str]:
    return {instrument.id: instrument.name for instrument in list_instruments(engine)}


def _sale_summary(engine: Engine, year: int, account_id: int | None) -> Report:
    return sale_summary_report(
        transactions_in_entry_order(engine), year, account_id, _instrument_names(engine), _account_names(engine)
    )


def _results(engine: Engine, year: int, account_id: int | None, history: Sequence[DayValue], today: date) -> Report:
    return results_report(history, list_accounts(engine), account_id, year, today, load_cpi(engine))


def _portfolio(engine: Engine, year: int, account_id: int | None, rates: LatestRates) -> Report:
    today = rates.today()
    day = min(date(year, 12, 31), today)
    snapshot = _todays_snapshot(engine, rates) if day == today else _snapshot_on(engine, day, today)
    return portfolio_report(snapshot, list_accounts(engine), account_id, _instrument_names(engine))


def _passive_income(engine: Engine, year: int, account_id: int | None, today: date) -> Report:
    return passive_income_report(
        income_items(engine, today), year, account_id, _instrument_names(engine), _account_names(engine)
    )


def _todays_snapshot(engine: Engine, rates: LatestRates) -> PortfolioSnapshot:
    view = todays_view(engine, rates)
    return PortfolioSnapshot(
        view.today,
        view.positions,
        view.foreign,
        view.cash,
        view.pln_prices,
        view.rates,
        {account_id: accrued.net for account_id, accrued in view.accrued.items()},
    )


def _snapshot_on(engine: Engine, day: date, today: date) -> PortfolioSnapshot:
    """The state on ``day``, replayed through the FIFO engine from the Transactions up to it and valued from the cached
    History prices; with no Transaction, an empty one."""
    inputs = history_inputs(engine, today)
    if inputs is None:
        return PortfolioSnapshot(day, [], [], {}, {}, {}, {})
    until = [t for t in inputs.transactions if t.date <= day]
    positions = open_positions(until)
    foreign = foreign_cash(until)
    accruals = inputs.accruals.on(day) if inputs.accruals is not None else {}
    return PortfolioSnapshot(
        day,
        positions,
        foreign,
        cash_balances(until),
        prices_on(
            inputs.transactions,
            inputs.instruments,
            inputs.prices,
            inputs.rates,
            inputs.bonds,
            day,
            {p.instrument_id for p in positions},
        ),
        rates_on(inputs.rates, {c.currency for c in foreign}, day),
        {account_id: accrued.net for account_id, accrued in accruals.items()},
    )


def _named(report: Report, year: int, account_id: int | None, accounts: Mapping[int, str]) -> str:
    return _file_name(report.name, year, account_id, accounts, "xlsx")


def _file_name(stem: str, year: int, account_id: int | None, accounts: Mapping[int, str], extension: str) -> str:
    name = f"{stem}-{year}"
    if account_id is not None:
        name += f"-{safe_file_part(accounts[account_id])}"
    return f"{name}.{extension}"
