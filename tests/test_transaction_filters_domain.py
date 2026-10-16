"""Filters and sorting of the Transakcje list (L-27): the values a column offers, which Transactions pass, and the
order a column header sorts in."""

from datetime import date
from decimal import Decimal

from financial_app.domain.transaction_filters import (
    NEWEST_FIRST,
    NO_FILTER,
    NO_INSTRUMENT,
    Column,
    Sort,
    TransactionFilter,
    account_options,
    instrument_options,
    type_options,
    view,
)
from financial_app.domain.transactions import Transaction, TransactionType

IKE, XTB, OLD = 1, 2, 3
CDR, VWCE = 10, 11
NAMES = {IKE: "IKE", XTB: "xtb", OLD: "Stare"}
INSTRUMENTS = {CDR: "CD Projekt", VWCE: "Vanguard"}


def _t(
    id: int,
    day: date,
    kind: TransactionType = TransactionType.DEPOSIT,
    amount: str = "100",
    account: int = IKE,
    comment: str = "",
    instrument: int | None = None,
    target: int | None = None,
) -> Transaction:
    if kind is TransactionType.BUY:
        return Transaction(
            account,
            day,
            kind,
            Decimal(amount),
            comment,
            instrument_id=instrument,
            quantity=Decimal(1),
            price=Decimal(amount),
            id=id,
        )
    return Transaction(account, day, kind, Decimal(amount), comment, target_account_id=target, id=id)


# Newest first, as list_transactions gives them
LISTED = [
    _t(5, date(2026, 10, 5), TransactionType.BUY, "250", XTB, "Druga transza", instrument=VWCE),
    _t(4, date(2026, 10, 5), TransactionType.CASH_TRANSFER, "50", IKE, "przelew", target=XTB),
    _t(3, date(2026, 9, 1), TransactionType.BUY, "900", IKE, "pierwsza", instrument=CDR),
    _t(2, date(2026, 8, 3), amount="3000", account=XTB, comment="wpłata"),
    _t(1, date(2026, 8, 3), amount="1000", comment="Wpłata startowa"),
]


def _ids(transactions: list[Transaction]) -> list[int]:
    return [t.id for t in transactions]


def _view(filters: TransactionFilter = NO_FILTER, sort: Sort = NEWEST_FIRST) -> list[int]:
    return _ids(view(LISTED, filters, sort, NAMES, INSTRUMENTS))


def test_the_default_keeps_every_transaction_newest_first() -> None:
    assert _view() == [5, 4, 3, 2, 1]
    assert not TransactionFilter().active


def test_the_date_sorts_oldest_first_with_same_day_ones_in_entry_order() -> None:
    assert _view(sort=Sort(Column.DATE, descending=False)) == [1, 2, 3, 4, 5]


def test_text_columns_sort_ignoring_case_and_the_amount_by_the_actual_amount() -> None:
    assert _view(sort=Sort(Column.ACCOUNT, descending=False)) == [4, 3, 1, 5, 2]
    assert _view(sort=Sort(Column.COMMENT, descending=False)) == [5, 3, 4, 2, 1]
    assert _view(sort=Sort(Column.AMOUNT)) == [2, 1, 3, 5, 4]
    assert _view(sort=Sort(Column.TYPE, descending=False)) == [4, 2, 1, 5, 3]


def test_transactions_without_an_instrument_sort_after_the_named_ones() -> None:
    assert _view(sort=Sort(Column.INSTRUMENT, descending=False)) == [3, 5, 4, 2, 1]


def test_the_lists_offer_the_values_present_sorted_by_name() -> None:
    assert account_options(LISTED, NAMES) == [(IKE, "IKE"), (XTB, "xtb")]
    assert type_options(LISTED) == [
        (TransactionType.DEPOSIT, TransactionType.DEPOSIT.label),
        (TransactionType.BUY, TransactionType.BUY.label),
        (TransactionType.CASH_TRANSFER, TransactionType.CASH_TRANSFER.label),
    ]
    assert instrument_options(LISTED, INSTRUMENTS) == [(CDR, "CD Projekt"), (VWCE, "Vanguard"), (NO_INSTRUMENT, None)]


def test_an_account_filter_keeps_transfers_to_the_chosen_account() -> None:
    assert _view(TransactionFilter(accounts=frozenset({XTB}))) == [5, 4, 2]


def test_type_and_instrument_filters_keep_the_chosen_values() -> None:
    assert _view(TransactionFilter(types=frozenset({TransactionType.BUY}))) == [5, 3]
    assert _view(TransactionFilter(instruments=frozenset({CDR, NO_INSTRUMENT}))) == [4, 3, 2, 1]


def test_amount_and_date_ranges_include_their_ends() -> None:
    assert _view(TransactionFilter(amount_from=Decimal(250), amount_to=Decimal(1000))) == [5, 3, 1]
    assert _view(TransactionFilter(amount_from=Decimal(1000))) == [2, 1]
    assert _view(TransactionFilter(date_from=date(2026, 9, 1), date_to=date(2026, 10, 4))) == [3]


def test_the_comment_filter_finds_contained_text_ignoring_case() -> None:
    assert _view(TransactionFilter(comment="WPŁATA")) == [2, 1]
    assert _view(TransactionFilter(comment="  ")) == [5, 4, 3, 2, 1]


def test_filters_combine_and_say_which_columns_they_filter() -> None:
    filters = TransactionFilter(accounts=frozenset({IKE}), comment="r")

    assert _view(filters) == [4, 3, 1]
    assert filters.active
    assert filters.is_set(Column.ACCOUNT) and filters.is_set(Column.COMMENT)
    assert not filters.is_set(Column.DATE)
    assert TransactionFilter(date_to=date(2026, 1, 1)).is_set(Column.DATE)
    assert TransactionFilter(amount_from=Decimal(0)).is_set(Column.AMOUNT)
