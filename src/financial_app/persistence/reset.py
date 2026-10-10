"""Clearing the portfolio (Ustawienia > Wyczyść dane): a fresh start for testing or a new portfolio."""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, delete, func, insert, select
from sqlalchemy.orm import Session

from financial_app.domain.instruments import DEFAULT_ASSET_CLASSES
from financial_app.persistence.backup import backup_database
from financial_app.persistence.models import (
    AccountCashCurrency,
    AccountRow,
    AssetClassRow,
    InstrumentRow,
    TransactionRow,
)
from financial_app.persistence.paths import BACKUPS_DIR


@dataclass(frozen=True)
class PortfolioCounts:
    """How much clearing would remove, for the warning shown before it."""

    accounts: int
    instruments: int
    transactions: int


def portfolio_counts(engine: Engine) -> PortfolioCounts:
    with Session(engine) as session:

        def count(model: type[AccountRow | InstrumentRow | TransactionRow]) -> int:
            return session.scalar(select(func.count()).select_from(model)) or 0

        return PortfolioCounts(count(AccountRow), count(InstrumentRow), count(TransactionRow))


def clear_portfolio(engine: Engine) -> Path | None:
    """Back the database up, then remove every Account, Instrument and Transaction and restore the default Asset
    Classes, all or nothing. The NBP Rate cache and the app settings stay. Returns the backup's path.

    The backup goes to the ``backups`` folder next to the database file, where the start-up backups are.
    """
    db_path = Path(engine.url.database or "")
    backup = backup_database(db_path, db_path.parent / BACKUPS_DIR)
    with Session(engine) as session, session.begin():
        # Children first, so the foreign keys never point at a removed row
        for model in (TransactionRow, AccountCashCurrency, AccountRow, InstrumentRow, AssetClassRow):
            session.execute(delete(model))
        session.execute(
            insert(AssetClassRow), [{"name": name, "position": i} for i, name in enumerate(DEFAULT_ASSET_CLASSES)]
        )
    return backup
