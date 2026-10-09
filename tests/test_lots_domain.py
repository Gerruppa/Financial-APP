"""The FIFO Lot engine and the Positions it produces (issue #13, spec 3.5, ADR-0003)."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.currencies import NbpRate
from financial_app.domain.lots import InsufficientQuantityError, open_positions
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell

IKE, XTB = 1, 2
PZU, CDR = 10, 20


def _buy(
    quantity: str, price: str, *, day: int = 1, fee: str = "0", account: int = IKE, instrument: int = PZU
) -> TransactionDraft:
    return buy_or_sell(
        account, date(2026, 1, day), TransactionType.BUY, instrument, Decimal(quantity), Decimal(price), Decimal(fee)
    )


def _sell(
    quantity: str, price: str, *, day: int = 1, fee: str = "0", account: int = IKE, instrument: int = PZU
) -> TransactionDraft:
    return buy_or_sell(
        account, date(2026, 1, day), TransactionType.SELL, instrument, Decimal(quantity), Decimal(price), Decimal(fee)
    )


def test_no_trades_give_no_positions() -> None:
    deposit = TransactionDraft(IKE, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(100))

    assert open_positions([deposit]) == []


def test_buy_opens_a_lot_with_the_commission_in_its_cost() -> None:
    [position] = open_positions([_buy("10", "50", fee="5")])

    assert (position.account_id, position.instrument_id) == (IKE, PZU)
    assert position.quantity == Decimal(10)
    assert position.cost == Decimal("505")
    assert position.average_price == Decimal("50.5")
    [lot] = position.lots
    assert (lot.date, lot.quantity, lot.cost) == (date(2026, 1, 1), Decimal(10), Decimal("505"))


def test_sell_consumes_the_oldest_lot_first() -> None:
    [position] = open_positions([_buy("10", "50", day=1), _buy("10", "60", day=2), _sell("10", "70", day=3)])

    [lot] = position.lots
    assert (lot.date, lot.quantity, lot.cost) == (date(2026, 1, 2), Decimal(10), Decimal(600))


def test_entry_order_does_not_matter_only_dates_do() -> None:
    [position] = open_positions([_sell("10", "70", day=3), _buy("10", "60", day=2), _buy("10", "50", day=1)])

    assert [lot.date.day for lot in position.lots] == [2]


def test_partial_sell_spans_several_lots_and_keeps_the_rest_pro_rata() -> None:
    trades = [_buy("10", "50", day=1, fee="10"), _buy("10", "60", day=2, fee="20"), _sell("15", "70", day=3, fee="7")]

    [position] = open_positions(trades)

    [lot] = position.lots
    assert lot.date == date(2026, 1, 2)
    assert lot.quantity == Decimal(5)
    # Half of the second Lot remains, with half of its cost incl. its commission; the sell fee does not touch Lots
    assert lot.cost == Decimal(310)


def test_selling_everything_closes_the_position() -> None:
    assert open_positions([_buy("10", "50"), _sell("4", "55", day=2), _sell("6", "60", day=3)]) == []


def test_same_day_buy_counts_before_a_sell_entered_earlier() -> None:
    [position] = open_positions([_buy("10", "50", day=1), _sell("12", "70", day=5), _buy("5", "55", day=5)])

    [lot] = position.lots
    assert (lot.date.day, lot.quantity) == (5, Decimal(3))


def test_same_day_lots_are_consumed_in_entry_order() -> None:
    [position] = open_positions([_buy("1", "100", day=5), _buy("1", "200", day=5), _sell("1", "300", day=5)])

    [lot] = position.lots
    assert lot.cost == Decimal(200)


def test_positions_are_kept_per_account_and_instrument() -> None:
    trades = [_buy("1", "10"), _buy("2", "20", account=XTB), _buy("3", "30", instrument=CDR), _sell("1", "20")]

    positions = open_positions(trades)

    assert {(p.account_id, p.instrument_id): p.quantity for p in positions} == {
        (XTB, PZU): Decimal(2),
        (IKE, CDR): Decimal(3),
    }


def test_sell_beyond_the_held_quantity_is_blocked() -> None:
    with pytest.raises(InsufficientQuantityError, match="05.01.2026") as caught:
        open_positions([_buy("10", "50", day=1), _sell("12", "60", day=5)])

    assert (caught.value.day, caught.value.held, caught.value.requested) == (date(2026, 1, 5), Decimal(10), Decimal(12))
    assert "10 szt." in str(caught.value) and "12 szt." in str(caught.value)


def test_sell_before_the_buy_date_is_blocked() -> None:
    with pytest.raises(InsufficientQuantityError):
        open_positions([_buy("10", "50", day=5), _sell("1", "60", day=4)])


def test_sell_on_another_account_is_not_covered() -> None:
    with pytest.raises(InsufficientQuantityError):
        open_positions([_buy("10", "50"), _sell("1", "60", account=XTB)])


def test_backdated_sell_that_uncovers_a_later_sell_is_blocked() -> None:
    trades = [_buy("10", "50", day=1), _sell("10", "60", day=20), _sell("5", "55", day=10)]

    with pytest.raises(InsufficientQuantityError, match="20.01.2026"):
        open_positions(trades)


def test_fractional_quantities_are_exact() -> None:
    [position] = open_positions([_buy("1", "300"), _sell("0.3", "310", day=2)])

    assert position.quantity == Decimal("0.7")
    assert position.cost == Decimal(210)


def test_value_and_result_come_from_a_price() -> None:
    [position] = open_positions([_buy("10", "50", fee="5")])

    assert position.value(Decimal(60)) == Decimal(600)
    assert position.result(Decimal(60)) == Decimal(95)
    assert position.result_percent(Decimal(60)).quantize(Decimal("0.01")) == Decimal("18.81")


def test_lot_carries_the_tax_cost_at_the_nbp_rate_next_to_the_actual_cost() -> None:
    usd = NbpRate("USD", Decimal(4), date(2026, 1, 1), "001/A/NBP/2026")
    buy = buy_or_sell(
        IKE,
        date(2026, 1, 2),
        TransactionType.BUY,
        PZU,
        Decimal(10),
        Decimal(10),
        Decimal(2),
        fx_rate=Decimal("4.1"),
        nbp_rate=usd,
    )

    [position] = open_positions([buy])

    [lot] = position.lots
    assert (lot.cost, lot.tax_cost) == (Decimal(412), Decimal(402))
    assert (position.cost, position.tax_cost) == (Decimal(412), Decimal(402))


def test_partial_sell_keeps_both_costs_pro_rata() -> None:
    [position] = open_positions([_buy("10", "50", fee="5"), _sell("4", "60", day=2)])

    [lot] = position.lots
    assert lot.cost == lot.tax_cost == Decimal(303)
