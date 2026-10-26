"""The report model (issue #240): Sell Summary and Wyniki as titled sections of typed rows for a calendar year and a
View Scope, from the single FIFO engine and the Wyniki calculations."""

from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.report import (
    NOTHING_TO_REPORT,
    Cell,
    Percent,
    Report,
    last_finished_year,
    results_report,
    sale_summary_report,
)
from financial_app.domain.sale_summary import in_view, sale_pairs
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell

IKE, XTB = 1, 2
PZU = 10
ACCOUNTS = [
    Account("IKE", "mBank", AccountType.IKE, ("PLN",), id=IKE),
    Account("XTB", "XTB", AccountType.REGULAR, ("PLN",), id=XTB),
]
ACCOUNT_NAMES = {IKE: "IKE", XTB: "XTB"}
INSTRUMENT_NAMES = {PZU: "PZU"}


def _measures(report: Report, title: str) -> dict[Cell, Cell]:
    """The Miara and Wartość columns of the section ``title``."""
    section = next(section for section in report.sections if section.title == title)
    return {row[0]: row[1] for row in section.rows}


def _trade(kind: TransactionType, quantity: str, price: str, day: date, account: int = IKE) -> TransactionDraft:
    return buy_or_sell(account, day, kind, PZU, Decimal(quantity), Decimal(price), Decimal(0))


def _sales() -> list[TransactionDraft]:
    return [
        _trade(TransactionType.BUY, "10", "50", date(2024, 1, 5)),
        _trade(TransactionType.SELL, "4", "60", date(2025, 3, 6)),
        _trade(TransactionType.BUY, "5", "20", date(2025, 4, 1), XTB),
        _trade(TransactionType.SELL, "5", "10", date(2025, 5, 1), XTB),
        _trade(TransactionType.SELL, "6", "70", date(2026, 2, 2)),
    ]


def test_the_last_finished_year_is_the_one_before_the_current() -> None:
    assert last_finished_year(date(2026, 1, 1)) == 2025
    assert last_finished_year(date(2026, 12, 31)) == 2025


def test_the_sell_summary_lists_the_years_sale_pairs_newest_first_with_typed_cells() -> None:
    report = sale_summary_report(_sales(), 2025, None, INSTRUMENT_NAMES, ACCOUNT_NAMES)

    pairs = next(section for section in report.sections if section.title == "Sprzedaże")
    assert [row[:2] for row in pairs.rows] == [("PZU", "XTB"), ("PZU", "IKE")]
    assert pairs.rows[1] == (
        "PZU",
        "IKE",
        date(2024, 1, 5),
        date(2025, 3, 6),
        Decimal(4),
        Decimal(200),
        Decimal(240),
        Decimal(40),
        Percent(Decimal("0.2")),
        426,
        Decimal(0),
        Decimal(40),
        Percent(Decimal("0.2")),
    )
    assert len(pairs.headers) == len(pairs.rows[0])


def test_the_sell_summary_figures_are_those_of_the_screens_sale_pairs() -> None:
    transactions = _sales()
    report = sale_summary_report(transactions, 2025, None, INSTRUMENT_NAMES, ACCOUNT_NAMES)

    on_screen = in_view(sale_pairs(transactions), None, date(2025, 1, 1), date(2025, 12, 31))
    pairs = next(section for section in report.sections if section.title == "Sprzedaże")
    assert [row[7] for row in pairs.rows] == [pair.result for pair in on_screen]
    totals = _measures(report, "Podsumowanie")
    assert totals["Wynik"] == sum(pair.result for pair in on_screen)
    assert totals["Zamknięte pary"] == 2


def test_one_account_gives_only_its_pairs_and_names_it_in_the_title() -> None:
    report = sale_summary_report(_sales(), 2025, XTB, INSTRUMENT_NAMES, ACCOUNT_NAMES)

    pairs = next(section for section in report.sections if section.title == "Sprzedaże")
    assert [row[1] for row in pairs.rows] == ["XTB"]
    assert "XTB" in report.title and "2025" in report.title
    assert "Wszystkie rachunki" in sale_summary_report(_sales(), 2025, None, INSTRUMENT_NAMES, ACCOUNT_NAMES).title


def test_a_year_without_sales_says_there_was_nothing_to_report() -> None:
    report = sale_summary_report(_sales(), 2023, None, INSTRUMENT_NAMES, ACCOUNT_NAMES)

    assert report.sections == ()
    assert report.notes == (NOTHING_TO_REPORT,)


def _on(day: date, ike: str, xtb: str = "0") -> DayValue:
    accounts = {IKE: Decimal(ike), XTB: Decimal(xtb)}
    return DayValue(day, accounts, {}, Decimal(2000), {IKE: Decimal(1000), XTB: Decimal(1000)}, frozenset())


def _history() -> list[DayValue]:
    return [
        _on(date(2025, 1, 2), "1000", "1000"),
        _on(date(2025, 6, 2), "1100", "1000"),
        _on(date(2025, 12, 31), "1210", "900"),
        _on(date(2026, 1, 5), "1300", "900"),
    ]


def test_wyniki_gives_the_years_results_and_a_row_for_the_total_and_each_account() -> None:
    report = results_report(_history(), ACCOUNTS, None, 2025, date(2026, 10, 26), [])

    summary = _measures(report, "Wyniki roku")
    assert summary["TWR"] == Percent(Decimal("0.055"))  # the Total over the year: 2000 to 2110
    accounts = next(section for section in report.sections if section.title == "Konta")
    assert [row[0] for row in accounts.rows] == ["Total", "IKE", "XTB"]
    assert accounts.rows[1][2] == Percent(Decimal("0.21"))  # IKE's TWR 1000 to 1210


def test_wyniki_of_one_account_follows_the_scope() -> None:
    report = results_report(_history(), ACCOUNTS, XTB, 2025, date(2026, 10, 26), [])

    summary = _measures(report, "Wyniki roku")
    assert summary["TWR"] == Percent(Decimal("-0.1"))
    accounts = next(section for section in report.sections if section.title == "Konta")
    assert [row[0] for row in accounts.rows] == ["XTB"]
    assert "XTB" in report.title


def test_wyniki_of_a_year_outside_history_or_without_history_has_nothing_to_report() -> None:
    assert results_report(_history(), ACCOUNTS, None, 2023, date(2026, 10, 26), []).notes == (NOTHING_TO_REPORT,)
    assert results_report([], ACCOUNTS, None, 2025, date(2026, 10, 26), []).notes == (NOTHING_TO_REPORT,)
