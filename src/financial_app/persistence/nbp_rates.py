"""The local cache of NBP Rates (D-1), keyed by currency and Transaction day (issue #15)."""

from datetime import date
from decimal import Decimal

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from financial_app.domain.currencies import NbpRate
from financial_app.persistence.models import NbpRateRow


def cached_rate(engine: Engine, currency: str, day: date) -> NbpRate | None:
    """The NBP Rate cached for a Transaction in ``currency`` dated ``day``, if any."""
    with Session(engine) as session:
        row = session.get(NbpRateRow, (currency, day))
        return None if row is None else NbpRate(row.currency, Decimal(row.rate), row.published_on, row.table)


def cache_rate(engine: Engine, day: date, rate: NbpRate) -> None:
    """Remember ``rate`` as the NBP Rate for Transactions dated ``day``."""
    with Session(engine) as session, session.begin():
        session.merge(
            NbpRateRow(
                currency=rate.currency, day=day, rate=str(rate.rate), published_on=rate.published_on, table=rate.table
            )
        )
