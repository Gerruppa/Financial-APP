"""The change since a Valuation Snapshot (issue #115, ADR-0008): the market change, the Net Deposits in between and
the market change as a fraction of the snapshot's value."""

from datetime import date, datetime
from decimal import Decimal

from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.valuation_snapshots import Figures, ValuationSnapshot, change_since, snapshot_figures

TAKEN_AT = datetime(2026, 10, 9, 18, 2)


def test_the_change_splits_into_the_market_and_the_net_deposits_in_between() -> None:
    snapshot = ValuationSnapshot(TAKEN_AT, Figures(value=Decimal(50000), net_deposits=Decimal(40000)))

    change = change_since(snapshot, Figures(value=Decimal(51234), net_deposits=Decimal(40500)))

    assert change.since == TAKEN_AT
    assert change.total == Decimal(1234)
    assert change.market == Decimal(734)
    assert change.net_deposits == Decimal(500)
    assert change.percent == Decimal("0.01468")


def test_a_withdrawal_in_between_is_negative_net_deposits_not_a_market_loss() -> None:
    snapshot = ValuationSnapshot(TAKEN_AT, Figures(value=Decimal(10000), net_deposits=Decimal(10000)))

    change = change_since(snapshot, Figures(value=Decimal(8000), net_deposits=Decimal(8000)))

    assert (change.total, change.market, change.net_deposits) == (Decimal(-2000), Decimal(0), Decimal(-2000))
    assert change.percent == Decimal(0)


def test_there_is_no_percent_of_a_snapshot_worth_nothing() -> None:
    snapshot = ValuationSnapshot(TAKEN_AT, Figures(value=Decimal(0), net_deposits=Decimal(0)))

    change = change_since(snapshot, Figures(value=Decimal(1010), net_deposits=Decimal(1000)))

    assert change.market == Decimal(10)
    assert change.percent is None


def test_the_figures_are_totals_and_each_accounts_value_with_historys_net_deposits() -> None:
    day = DayValue(
        day=date(2026, 10, 9),
        accounts={1: Decimal(900), 2: Decimal(100)},
        classes={},
        net_deposits=Decimal(1000),
        account_net_deposits={1: Decimal(1200), 2: Decimal(-200)},
        unpriced=frozenset(),
    )

    figures = snapshot_figures({1: Decimal(950), 2: Decimal(150), 3: Decimal(0)}, day)

    assert figures == {
        None: Figures(Decimal(1100), Decimal(1000)),
        1: Figures(Decimal(950), Decimal(1200)),
        2: Figures(Decimal(150), Decimal(-200)),
        3: Figures(Decimal(0), Decimal(0)),
    }
