"""The Sell Summary (issue #92, spec 10): Sale Pairs from the single FIFO engine, the Dividends attributed to them and
the statistics of the closed positions."""

from datetime import date
from decimal import Decimal

from financial_app.domain.sale_summary import (
    SalePair,
    in_view,
    sale_pairs,
    sale_stats,
)
from financial_app.domain.transactions import (
    SplitRatio,
    TransactionDraft,
    TransactionType,
    buy_or_sell,
    dividend,
    drip,
    split,
)

IKE, XTB = 1, 2
PZU, CDR, EDO = 10, 20, 30


def _buy(
    quantity: str, price: str, day: date, fee: str = "0", account: int = IKE, instrument: int = PZU
) -> TransactionDraft:
    return buy_or_sell(account, day, TransactionType.BUY, instrument, Decimal(quantity), Decimal(price), Decimal(fee))


def _sell(
    quantity: str, price: str, day: date, fee: str = "0", account: int = IKE, instrument: int = PZU
) -> TransactionDraft:
    return buy_or_sell(account, day, TransactionType.SELL, instrument, Decimal(quantity), Decimal(price), Decimal(fee))


def _pair_values(pair: SalePair) -> tuple[date, date, Decimal, Decimal, Decimal]:
    return pair.bought_on, pair.sold_on, pair.quantity, pair.cost, pair.revenue


def test_a_sell_pairs_with_the_buy_it_closes() -> None:
    [pair] = sale_pairs([_buy("10", "50", date(2026, 1, 5), fee="5"), _sell("10", "60", date(2026, 3, 6), fee="5")])

    assert (pair.account_id, pair.instrument_id) == (IKE, PZU)
    assert _pair_values(pair) == (date(2026, 1, 5), date(2026, 3, 6), Decimal(10), Decimal(505), Decimal(595))
    assert pair.result == Decimal(90)
    assert pair.return_rate == Decimal(90) / Decimal(505)
    assert pair.days_held == 60
    assert pair.dividends == 0
    assert pair.result_with_dividends == Decimal(90)


def test_a_sell_across_two_lots_gives_a_pair_for_each_oldest_first() -> None:
    pairs = sale_pairs(
        [
            _buy("10", "50", date(2026, 1, 5)),
            _buy("10", "70", date(2026, 2, 5)),
            _sell("15", "60", date(2026, 3, 5), fee="15"),
        ]
    )

    # The commission splits by units: 10 for the first Lot, 5 for the second
    assert [_pair_values(pair) for pair in pairs] == [
        (date(2026, 1, 5), date(2026, 3, 5), Decimal(10), Decimal(500), Decimal(590)),
        (date(2026, 2, 5), date(2026, 3, 5), Decimal(5), Decimal(350), Decimal(295)),
    ]
    assert [pair.result for pair in pairs] == [Decimal(90), Decimal(-55)]


def test_a_split_before_the_sale_leaves_the_cost_and_counts_the_new_units() -> None:
    [pair] = sale_pairs(
        [
            _buy("10", "50", date(2026, 1, 5)),
            split(IKE, date(2026, 2, 1), PZU, SplitRatio(5, 1)),
            _sell("50", "12", date(2026, 3, 5)),
        ]
    )

    assert _pair_values(pair) == (date(2026, 1, 5), date(2026, 3, 5), Decimal(50), Decimal(500), Decimal(600))


def test_a_reinvested_dividend_is_a_lot_of_its_own_with_the_dividend_attributed_to_the_bought_units() -> None:
    pairs = sale_pairs(
        [
            _buy("10", "50", date(2026, 1, 5)),
            drip(IKE, date(2026, 2, 5), PZU, Decimal(1), Decimal(55)),
            _sell("11", "60", date(2026, 3, 5)),
        ]
    )

    assert [_pair_values(pair) for pair in pairs] == [
        (date(2026, 1, 5), date(2026, 3, 5), Decimal(10), Decimal(500), Decimal(600)),
        (date(2026, 2, 5), date(2026, 3, 5), Decimal(1), Decimal(55), Decimal(60)),
    ]
    assert [pair.dividends for pair in pairs] == [Decimal(55), Decimal(0)]


def test_a_dividend_goes_to_the_units_held_the_day_before_in_proportion() -> None:
    # 15 units held on 1.03: 10 of the first Lot (sold on 5.03) and 5 of the second (still held)
    [pair] = sale_pairs(
        [
            _buy("10", "50", date(2026, 1, 5)),
            _buy("5", "50", date(2026, 2, 5)),
            dividend(IKE, date(2026, 3, 1), Decimal(30), instrument_id=PZU),
            _sell("10", "60", date(2026, 3, 5)),
        ]
    )

    assert pair.dividends == Decimal(20)
    assert pair.result_with_dividends == Decimal(120)
    assert pair.return_with_dividends == Decimal(120) / Decimal(500)


def test_a_dividend_on_the_sale_day_is_still_the_pairs_and_one_on_the_buy_day_is_not() -> None:
    [pair] = sale_pairs(
        [
            dividend(IKE, date(2026, 1, 5), Decimal(7), instrument_id=PZU),
            _buy("10", "50", date(2026, 1, 5)),
            dividend(IKE, date(2026, 3, 5), Decimal(10), instrument_id=PZU),
            _sell("10", "60", date(2026, 3, 5)),
        ]
    )

    assert pair.dividends == Decimal(10)


def test_a_dividend_paid_soon_after_the_whole_position_was_sold_is_the_last_sales() -> None:
    pairs = sale_pairs(
        [
            _buy("10", "50", date(2026, 1, 5)),
            _buy("10", "50", date(2026, 1, 6)),
            _sell("20", "60", date(2026, 3, 5)),
            dividend(IKE, date(2026, 4, 20), Decimal(40), instrument_id=PZU),
        ]
    )

    assert [pair.dividends for pair in pairs] == [Decimal(20), Decimal(20)]


def test_a_dividend_long_after_the_sale_or_after_buying_again_is_not_the_pairs() -> None:
    pairs = sale_pairs(
        [
            _buy("10", "50", date(2026, 1, 5)),
            _sell("10", "60", date(2026, 3, 5)),
            dividend(IKE, date(2026, 7, 1), Decimal(40), instrument_id=PZU),
            _buy("10", "50", date(2026, 8, 5), instrument=CDR),
            _sell("10", "60", date(2026, 9, 5), instrument=CDR),
            _buy("10", "50", date(2026, 9, 10), instrument=CDR),
            dividend(IKE, date(2026, 9, 20), Decimal(40), instrument_id=CDR),
        ]
    )

    assert [pair.dividends for pair in pairs] == [Decimal(0), Decimal(0)]


def test_a_dividend_of_another_account_is_not_the_pairs() -> None:
    [pair] = sale_pairs(
        [
            _buy("10", "50", date(2026, 1, 5)),
            _buy("10", "50", date(2026, 1, 5), account=XTB),
            dividend(XTB, date(2026, 2, 1), Decimal(40), instrument_id=PZU),
            _sell("10", "60", date(2026, 3, 5)),
        ]
    )

    assert pair.dividends == 0


def test_a_coupon_goes_to_the_lot_it_names() -> None:
    first = _buy("10", "100", date(2026, 1, 5), instrument=EDO).with_id(1)
    second = _buy("10", "100", date(2026, 1, 6), instrument=EDO).with_id(2)
    coupon = dividend(IKE, date(2027, 1, 5), Decimal(50), lot_id=1).with_id(3)
    redemption = buy_or_sell(
        IKE, date(2027, 2, 1), TransactionType.SELL, EDO, Decimal(10), Decimal(105), lot_id=2
    ).with_id(4)
    sold_first = _sell("10", "106", date(2027, 3, 1), instrument=EDO).with_id(5)

    pairs = sale_pairs([first, second, coupon, redemption, sold_first])

    assert [(pair.bought_on, pair.dividends) for pair in pairs] == [
        (date(2026, 1, 6), Decimal(0)),
        (date(2026, 1, 5), Decimal(50)),
    ]


def test_the_statistics_of_the_closed_positions() -> None:
    pairs = sale_pairs(
        [
            _buy("10", "50", date(2026, 1, 1)),
            _sell("10", "60", date(2026, 1, 11)),
            _buy("10", "50", date(2026, 1, 1), instrument=CDR),
            _sell("10", "40", date(2026, 1, 31), instrument=CDR),
            _buy("10", "50", date(2026, 2, 1)),
            dividend(IKE, date(2026, 2, 5), Decimal(5), instrument_id=PZU),
            _sell("10", "51", date(2026, 2, 21)),
        ]
    )

    stats = sale_stats(pairs)

    assert stats is not None
    assert stats.count == 3
    assert stats.win_rate == Decimal(2) / Decimal(3)
    assert stats.average_days == Decimal(20)
    assert stats.best is not None and stats.best.instrument_id == PZU and stats.best.result == Decimal(100)
    assert stats.worst is not None and stats.worst.instrument_id == CDR and stats.worst.result == Decimal(-100)
    assert (stats.cost, stats.revenue, stats.result, stats.dividends) == (
        Decimal(1500),
        Decimal(1510),
        Decimal(10),
        Decimal(5),
    )
    assert stats.result_with_dividends == Decimal(15)
    assert sale_stats([]) is None


def test_the_view_keeps_the_scopes_pairs_sold_within_the_period_newest_first() -> None:
    pairs = sale_pairs(
        [
            _buy("10", "50", date(2026, 1, 1)),
            _sell("5", "60", date(2026, 2, 1)),
            _sell("5", "60", date(2026, 4, 1)),
            _buy("10", "50", date(2026, 1, 1), account=XTB),
            _sell("10", "60", date(2026, 3, 1), account=XTB),
        ]
    )

    assert [p.sold_on for p in in_view(pairs, None, date(2026, 2, 1), date(2026, 3, 31))] == [
        date(2026, 3, 1),
        date(2026, 2, 1),
    ]
    assert [p.sold_on for p in in_view(pairs, IKE, date(2026, 1, 1), date(2026, 12, 31))] == [
        date(2026, 4, 1),
        date(2026, 2, 1),
    ]
