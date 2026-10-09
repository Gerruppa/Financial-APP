"""Splits, Cash Transfers and Security Transfers in the FIFO engine and Cash Balances (issue #19, spec 3.3, 3.5)."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.lots import InsufficientQuantityError, SplitBeforeFirstBuyError, open_positions
from financial_app.domain.transactions import (
    SplitRatio,
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    cash_balances,
    cash_transfer,
    lowest_cash_balance,
    security_transfer,
    split,
)

IKE, XTB = 1, 2
PZU, CDR = 10, 20


def _buy(quantity: str, price: str, *, day: int = 1, fee: str = "0", account: int = IKE) -> TransactionDraft:
    return buy_or_sell(
        account, date(2026, 1, day), TransactionType.BUY, PZU, Decimal(quantity), Decimal(price), Decimal(fee)
    )


def _sell(quantity: str, price: str, *, day: int = 1, account: int = IKE) -> TransactionDraft:
    return buy_or_sell(account, date(2026, 1, day), TransactionType.SELL, PZU, Decimal(quantity), Decimal(price))


def _split(new: int, old: int, *, day: int, account: int = IKE) -> TransactionDraft:
    return split(account, date(2026, 1, day), PZU, SplitRatio(new, old))


def test_split_changes_quantity_and_unit_price_but_not_the_total_cost() -> None:
    [position] = open_positions([_buy("10", "50", day=1, fee="5"), _split(2, 1, day=2)])

    assert position.quantity == Decimal(20)
    # 505 zł for 10 units at 50,50 becomes 505 zł for 20 units at 25,25: the commission is not rescaled
    assert position.cost == Decimal(505)
    assert position.average_price == Decimal("25.25")
    [lot] = position.lots
    assert lot.date == date(2026, 1, 1)


def test_split_rescales_every_open_lot_and_later_sells_count_in_new_units() -> None:
    trades = [_buy("10", "50", day=1), _buy("10", "60", day=2), _split(3, 1, day=3), _sell("45", "25", day=4)]

    [position] = open_positions(trades)

    [lot] = position.lots
    assert (lot.date, lot.quantity, lot.cost) == (date(2026, 1, 2), Decimal(15), Decimal(300))


def test_reverse_split_divides_quantity() -> None:
    [position] = open_positions([_buy("10", "5", day=1), _split(1, 5, day=2)])

    assert (position.quantity, position.cost) == (Decimal(2), Decimal(50))


def test_reverse_split_by_a_ratio_without_a_finite_decimal_keeps_whole_units() -> None:
    # 1/3 has no finite decimal, so 3 units must become exactly 1, not 0,999…, or selling it would be blocked
    assert open_positions([_buy("3", "10", day=1), _split(1, 3, day=2), _sell("1", "35", day=3)]) == []


def test_split_counts_before_a_buy_on_the_same_day() -> None:
    [position] = open_positions([_buy("10", "50", day=1), _buy("10", "30", day=2), _split(2, 1, day=2)])

    assert [lot.quantity for lot in position.lots] == [Decimal(20), Decimal(10)]


def test_split_before_the_first_buy_is_blocked() -> None:
    with pytest.raises(SplitBeforeFirstBuyError, match="02.01.2026"):
        open_positions([_split(2, 1, day=2), _buy("10", "50", day=3)])


def test_split_on_another_account_does_not_count_as_after_a_buy() -> None:
    with pytest.raises(SplitBeforeFirstBuyError):
        open_positions([_buy("10", "50", day=1), _split(2, 1, day=2, account=XTB)])


@pytest.mark.parametrize(("new", "old"), [(0, 1), (2, 0), (-2, 1), (1, 1)])
def test_split_ratio_needs_two_different_positive_whole_numbers(new: int, old: int) -> None:
    with pytest.raises(TransactionError):
        SplitRatio(new, old)


def test_split_moves_no_cash_and_has_no_amount() -> None:
    draft = _split(2, 1, day=2)

    assert (draft.actual_amount, draft.cash_change, draft.tax_amount) == (Decimal(0), Decimal(0), Decimal(0))
    assert str(draft.split_ratio) == "2:1"


def _transfer(quantity: str, *, day: int, source: int = IKE, target: int = XTB) -> TransactionDraft:
    return security_transfer(source, date(2026, 1, day), target, PZU, Decimal(quantity))


def test_security_transfer_moves_lots_with_their_original_dates_and_costs() -> None:
    trades = [_buy("10", "50", day=1, fee="10"), _buy("10", "60", day=2), _transfer("15", day=5)]

    positions = {p.account_id: p for p in open_positions(trades)}

    [left] = positions[IKE].lots
    assert (left.date, left.quantity, left.cost) == (date(2026, 1, 2), Decimal(5), Decimal(300))
    moved = positions[XTB].lots
    assert [(lot.date, lot.quantity, lot.cost) for lot in moved] == [
        (date(2026, 1, 1), Decimal(10), Decimal(510)),
        (date(2026, 1, 2), Decimal(5), Decimal(300)),
    ]


def test_sell_after_a_transfer_takes_the_transferred_lots_first_by_their_dates() -> None:
    trades = [
        _buy("10", "50", day=1),
        _buy("10", "80", day=3, account=XTB),
        _transfer("10", day=5),
        _sell("12", "90", day=6, account=XTB),
    ]

    [position] = open_positions(trades)

    assert position.account_id == XTB
    [lot] = position.lots
    # The 10 units bought on 1 January on IKE were older than XTB's own, so they went first
    assert (lot.date, lot.quantity, lot.cost) == (date(2026, 1, 3), Decimal(8), Decimal(640))


def test_transfer_of_more_than_held_is_blocked() -> None:
    with pytest.raises(InsufficientQuantityError, match="Transfer bez pokrycia"):
        open_positions([_buy("10", "50", day=1), _transfer("11", day=2)])


def test_split_on_the_target_account_counts_after_a_transfer_in() -> None:
    [position] = open_positions([_buy("10", "50", day=1), _transfer("10", day=2), _split(2, 1, day=3, account=XTB)])

    assert (position.account_id, position.quantity, position.cost) == (XTB, Decimal(20), Decimal(500))


def test_transfers_need_another_target_account() -> None:
    with pytest.raises(TransactionError, match="inne"):
        _transfer("1", day=1, target=IKE)
    with pytest.raises(TransactionError):
        TransactionDraft(IKE, date(2026, 1, 1), TransactionType.CASH_TRANSFER, Decimal(100))


def test_cash_transfer_moves_cash_from_the_source_to_the_target_account() -> None:
    deposit = TransactionDraft(IKE, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(1000))
    transfer = cash_transfer(IKE, date(2026, 1, 2), XTB, Decimal(400))

    assert cash_balances([deposit, transfer]) == {IKE: Decimal(600), XTB: Decimal(400)}
    assert lowest_cash_balance([transfer], XTB, start=date(2026, 1, 1)) == 0
    assert lowest_cash_balance([transfer], IKE, start=date(2026, 1, 1)) == Decimal(-400)


def test_security_transfer_moves_no_cash() -> None:
    assert cash_balances([_transfer("1", day=1)]).get(IKE, Decimal(0)) == 0


def test_split_draft_needs_its_ratio_and_instrument() -> None:
    with pytest.raises(TransactionError):
        TransactionDraft(IKE, date(2026, 1, 2), TransactionType.SPLIT, Decimal(0), instrument_id=PZU)
    with pytest.raises(TransactionError):
        TransactionDraft(IKE, date(2026, 1, 2), TransactionType.SPLIT, Decimal(0), split_ratio=SplitRatio(2, 1))
