"""The Account ranking and the Accounts treemap of the Total Dashboard (issue #89, spec 5): XIRR, TWR, P&L, Net
Deposits and costs per Account, sortable, the best and worst marked."""

from decimal import Decimal

from financial_app.domain.account_ranking import (
    RankingColumn,
    best_and_worst,
    ranking,
    sort_ranking,
    treemap_tiles,
)
from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.dashboard import AccountRow, Totals


def _row(
    account_id: int,
    name: str,
    *,
    value: str,
    net_deposits: str | None,
    xirr: str | None = None,
    costs: str = "0",
    tax: str = "0",
) -> AccountRow:
    totals = Totals(
        net_deposits=None if net_deposits is None else Decimal(net_deposits),
        cash=Decimal(value),
        open_positions=Decimal(0),
        unrealized=Decimal(0),
        realized=Decimal(0),
        dividends=Decimal(0),
        costs=Decimal(costs),
        xirr=None if xirr is None else Decimal(xirr),
        twr=None if xirr is None else Decimal(xirr) / 2,
        estimated_tax=Decimal(tax),
    )
    return AccountRow(Account(name, "", AccountType.REGULAR, ("PLN",), id=account_id), totals)


ROWS = [
    _row(1, "IKE", value="1200", net_deposits="1000", xirr="0.2", costs="10"),
    _row(2, "XTB", value="900", net_deposits="1000", xirr="-0.1", costs="30", tax="0"),
    _row(3, "mBank", value="500", net_deposits="450", xirr=None, costs="5", tax="9.5"),
]


def test_each_account_has_its_figures_and_the_profit_is_value_less_net_deposits() -> None:
    [ike, *_] = ranking(ROWS)

    assert (ike.account.name, ike.xirr, ike.twr, ike.profit, ike.net_deposits, ike.costs) == (
        "IKE",
        Decimal("0.2"),
        Decimal("0.1"),
        Decimal(200),
        Decimal(1000),
        Decimal(10),
    )


def test_after_tax_takes_the_estimated_tax_off_the_profit() -> None:
    rows = ranking(ROWS, after_tax=True)

    assert [row.profit for row in rows] == [Decimal(200), Decimal(-100), Decimal("40.5")]


def test_sorting_by_a_column_puts_accounts_without_a_figure_last_either_way() -> None:
    rows = ranking(ROWS)

    assert [r.account.name for r in sort_ranking(rows, RankingColumn.XIRR)] == ["IKE", "XTB", "mBank"]
    assert [r.account.name for r in sort_ranking(rows, RankingColumn.XIRR, descending=False)] == [
        "XTB",
        "IKE",
        "mBank",
    ]
    assert [r.account.name for r in sort_ranking(rows, RankingColumn.COSTS)] == ["XTB", "IKE", "mBank"]


def test_best_and_worst_follow_whether_more_is_better() -> None:
    rows = ranking(ROWS)

    assert best_and_worst(rows, RankingColumn.XIRR) == (1, 2)
    assert best_and_worst(rows, RankingColumn.PROFIT) == (1, 2)
    assert best_and_worst(rows, RankingColumn.COSTS) == (3, 2)  # the lowest costs are best
    assert best_and_worst(rows, RankingColumn.NET_DEPOSITS) == (None, None)  # neither better nor worse


def test_no_best_or_worst_without_two_different_figures() -> None:
    rows = ranking([ROWS[0], _row(4, "Inne", value="1", net_deposits="1", xirr=None, costs="10")])

    assert best_and_worst(rows, RankingColumn.XIRR) == (None, None)
    assert best_and_worst(rows, RankingColumn.COSTS) == (None, None)


def test_profit_waits_for_history() -> None:
    [row] = ranking([_row(1, "IKE", value="1200", net_deposits=None)])

    assert row.profit is None


def test_the_treemap_has_a_tile_per_account_holding_something_with_its_return_on_net_deposits() -> None:
    rows = [*ROWS, _row(4, "Puste", value="0", net_deposits="0")]

    tiles = treemap_tiles(ranking(rows))

    assert [(t.account.id, t.value, t.profit, t.profit_share) for t in tiles] == [
        (1, Decimal(1200), Decimal(200), Decimal("0.2")),
        (2, Decimal(900), Decimal(-100), Decimal("-0.1")),
        (3, Decimal(500), Decimal(50), Decimal(50) / Decimal(450)),
    ]


def test_a_tile_of_an_account_that_took_out_more_than_it_paid_in_compares_profit_with_value() -> None:
    [tile] = treemap_tiles(ranking([_row(1, "IKE", value="100", net_deposits="-50")]))

    assert tile.profit_share == Decimal("1.5")


def test_a_treemap_tile_has_no_return_while_history_is_computed() -> None:
    [tile] = treemap_tiles(ranking([_row(1, "IKE", value="100", net_deposits=None)]))

    assert tile.profit_share is None
