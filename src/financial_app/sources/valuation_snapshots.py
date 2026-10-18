"""Taking a Valuation Snapshot after a Successful Refresh and the Dashboard's change since one (issue #115,
ADR-0008)."""

from datetime import date, datetime

from sqlalchemy import Engine

from financial_app.domain.dashboard import Totals
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.valuation_snapshots import Figures, SnapshotChange, change_since, snapshot_figures
from financial_app.persistence.valuation_snapshots import save_snapshot, snapshot_before
from financial_app.sources.current_prices import LatestRates
from financial_app.sources.todays_view import todays_view


def take_snapshot(engine: Engine, rates: LatestRates, history: list[DayValue], taken_at: datetime) -> None:
    """Snapshot Total and each Account at ``taken_at``: today's values as the Dashboard shows them, the Net Deposits
    of ``history``'s last day (History computed after the refresh)."""
    view = todays_view(engine, rates)
    values = {account.id: view.account_value(account).value for account in view.accounts}
    save_snapshot(engine, taken_at, snapshot_figures(values, history[-1]))


def change_since_snapshot(engine: Engine, account_id: int | None, totals: Totals, today: date) -> SnapshotChange | None:
    """The View Scope's change from the newest snapshot of a day before ``today`` to its Dashboard ``totals``;
    ``None`` without such a snapshot or while History, and so the Net Deposits, is computed."""
    if totals.net_deposits is None:
        return None
    snapshot = snapshot_before(engine, today, account_id)
    if snapshot is None:
        return None
    return change_since(snapshot, Figures(totals.value, totals.net_deposits))
