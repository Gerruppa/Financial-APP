"""The Account ranking and the Accounts treemap of the Total Dashboard (issue #89, spec 5 and 6.1).

Each Account shown in the Dashboard's Account table gets its XIRR and TWR over the period, its P&L (value less Net
Deposits, as the sheet's "Zysk / strata"; less the estimated Belka with the "po podatku" toggle), its Net Deposits and
its commissions and costs. The ranking sorts by any of them and marks the best and the worst: the highest return or
P&L, the lowest costs; Net Deposits are neither better nor worse. The treemap sizes each Account holding something by
its value and colours it by its P&L against its Net Deposits.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from financial_app.domain.accounts import Account
from financial_app.domain.dashboard import AccountRow


class RankingColumn(StrEnum):
    """A column of the ranking; the value is its UI marker."""

    XIRR = "xirr"
    TWR = "twr"
    PROFIT = "profit"
    NET_DEPOSITS = "net-deposits"
    COSTS = "costs"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def better(self) -> int:
        """1 when more is better, -1 when less is, 0 when neither."""
        return _BETTER.get(self, 1)


_LABELS = {
    RankingColumn.XIRR: "XIRR",
    RankingColumn.TWR: "TWR",
    RankingColumn.PROFIT: "Zysk / strata",
    RankingColumn.NET_DEPOSITS: "Wpłaty netto",
    RankingColumn.COSTS: "Prowizje i koszty",
}
_BETTER = {RankingColumn.NET_DEPOSITS: 0, RankingColumn.COSTS: -1}


@dataclass(frozen=True)
class RankingRow:
    """An Account's figures; ``None`` while History is computed (or, for XIRR, without a rate)."""

    account: Account
    value: Decimal
    xirr: Decimal | None
    twr: Decimal | None
    profit: Decimal | None
    net_deposits: Decimal | None
    costs: Decimal

    def figure(self, column: RankingColumn) -> Decimal | None:
        figures = {
            RankingColumn.XIRR: self.xirr,
            RankingColumn.TWR: self.twr,
            RankingColumn.PROFIT: self.profit,
            RankingColumn.NET_DEPOSITS: self.net_deposits,
            RankingColumn.COSTS: self.costs,
        }
        return figures[column]


@dataclass(frozen=True)
class TreemapTile:
    """An Account's tile: sized by ``value``, coloured by ``profit_share``, its P&L as a fraction of its Net Deposits,
    or of its value when it has taken out more than it paid in (``None`` without P&L)."""

    account: Account
    value: Decimal
    profit: Decimal | None
    profit_share: Decimal | None


def ranking(rows: Sequence[AccountRow], after_tax: bool = False) -> list[RankingRow]:
    """A ranking row per Account row of the Dashboard, in their order; ``after_tax`` takes each Account's estimated
    Belka off its P&L."""

    return [
        RankingRow(
            row.account,
            row.totals.value,
            row.totals.xirr,
            row.totals.twr,
            row.totals.profit_after(after_tax),
            row.totals.net_deposits,
            row.totals.costs,
        )
        for row in rows
    ]


def sort_ranking(rows: Sequence[RankingRow], column: RankingColumn, descending: bool = True) -> list[RankingRow]:
    """The rows by ``column``, highest first unless not ``descending``; rows without the figure last either way."""
    known = [row for row in rows if row.figure(column) is not None]
    unknown = [row for row in rows if row.figure(column) is None]
    known.sort(key=lambda row: row.figure(column) or Decimal(0), reverse=descending)
    return [*known, *unknown]


def best_and_worst(rows: Sequence[RankingRow], column: RankingColumn) -> tuple[int | None, int | None]:
    """The ids of the Accounts with the best and the worst figure in ``column``; neither when the column is neither
    better nor worse or fewer than two different figures are known."""
    figures = [(figure, row.account.id) for row in rows if (figure := row.figure(column)) is not None]
    if not column.better or len({figure for figure, _ in figures}) < 2:
        return None, None
    highest = max(figures, key=lambda item: item[0])[1]
    lowest = min(figures, key=lambda item: item[0])[1]
    return (highest, lowest) if column.better > 0 else (lowest, highest)


def treemap_tiles(rows: Sequence[RankingRow]) -> list[TreemapTile]:
    """A tile per Account holding something (a positive value), in the rows' order."""
    return [
        TreemapTile(row.account, row.value, row.profit, _share(row.profit, row.net_deposits, row.value))
        for row in rows
        if row.value > 0
    ]


def _share(profit: Decimal | None, net_deposits: Decimal | None, value: Decimal) -> Decimal | None:
    if profit is None or net_deposits is None:
        return None
    return profit / (net_deposits if net_deposits > 0 else value)
