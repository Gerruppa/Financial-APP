"""Valuation Snapshots (issue #115, ADR-0008): Total's and each Account's value and Net Deposits as the Dashboard
showed them after a Successful Refresh, and the change since one split into the market change and the Net Deposits
in between.

The value is the Dashboard's (with Manual Prices, before tax) and the Net Deposits History's, so a Transaction
entered later with a date in the gap counts as a Deposit or Withdrawal rather than as market change.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from financial_app.domain.portfolio_history import DayValue


@dataclass(frozen=True)
class Figures:
    """A View Scope's value and Net Deposits, in PLN."""

    value: Decimal
    net_deposits: Decimal


@dataclass(frozen=True)
class ValuationSnapshot:
    """One View Scope's ``figures`` as they were at ``taken_at``."""

    taken_at: datetime
    figures: Figures


@dataclass(frozen=True)
class SnapshotChange:
    """The change in value ``since`` a snapshot: ``total`` = ``market`` + ``net_deposits``; ``percent`` is the market
    change as a fraction of the snapshot's value, ``None`` when it was worth nothing."""

    since: datetime
    total: Decimal
    market: Decimal
    net_deposits: Decimal
    percent: Decimal | None


def change_since(snapshot: ValuationSnapshot, now: Figures) -> SnapshotChange:
    """The change from ``snapshot`` to the figures ``now``: the Net Deposits in between are not market change."""
    before = snapshot.figures
    total = now.value - before.value
    net_deposits = now.net_deposits - before.net_deposits
    market = total - net_deposits
    percent = market / before.value if before.value else None
    return SnapshotChange(snapshot.taken_at, total, market, net_deposits, percent)


def snapshot_figures(values: Mapping[int, Decimal], day: DayValue) -> dict[int | None, Figures]:
    """The figures to snapshot by View Scope (``None`` for Total): each Account's value today from ``values`` (by
    Account id) with the Net Deposits of History's last ``day``; Total's value is the Accounts' sum."""
    figures: dict[int | None, Figures] = {
        None: Figures(sum(values.values(), Decimal(0)), day.net_deposits),
    }
    for account_id, value in values.items():
        figures[account_id] = Figures(value, day.account_net_deposits.get(account_id, Decimal(0)))
    return figures
