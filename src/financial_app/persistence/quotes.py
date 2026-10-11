"""The Instruments' daily Quotes from the Price Sources (issue #30, spec 4.1).

One Quote per Instrument and day: a later fetch on the same day replaces it, and the newest is the current price.
Price history (Stage 4) fills older days into the same table.
"""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from financial_app.domain.prices import STOOQ, Quote
from financial_app.persistence.models import AppSetting, PriceFailureRow, QuoteRow
from financial_app.persistence.settings import load_setting

# The app settings holding the time of the last refresh and of the last one that was a success
REFRESHED_AT = "prices_refreshed_at"
SUCCEEDED_AT = "prices_succeeded_at"


def save_quote(engine: Engine, instrument_id: int, quote: Quote, fetched_at: datetime) -> None:
    with Session(engine) as session, session.begin():
        session.merge(
            QuoteRow(
                instrument_id=instrument_id,
                day=quote.day,
                price=str(quote.price),
                currency=quote.currency,
                source=quote.source,
                fetched_at=fetched_at,
            )
        )


def latest_quotes(engine: Engine) -> dict[int, Quote]:
    """Each Instrument's newest Quote, by Instrument id; Stooq's price history never is one (spec 4.1)."""
    with Session(engine) as session:
        newest = (
            select(QuoteRow.instrument_id, func.max(QuoteRow.day).label("day"))
            .where(QuoteRow.source != STOOQ)
            .group_by(QuoteRow.instrument_id)
            .subquery()
        )
        rows = session.scalars(
            select(QuoteRow).join(
                newest, (QuoteRow.instrument_id == newest.c.instrument_id) & (QuoteRow.day == newest.c.day)
            )
        )
        return {row.instrument_id: Quote(Decimal(row.price), row.currency, row.day, row.source) for row in rows}


def save_refresh(
    engine: Engine, refreshed_at: datetime, failures: Mapping[int, Mapping[str, str]], succeeded: bool
) -> None:
    """Record a refresh: its time and, by Instrument id, why each source failed for the Instruments no source gave a
    Quote for. It replaces the previous refresh's failures, so a later success clears them. Only a refresh that
    ``succeeded`` becomes the last successful one."""
    with Session(engine) as session, session.begin():
        session.execute(delete(PriceFailureRow))
        session.add_all(
            PriceFailureRow(instrument_id=instrument_id, source=source, position=position, reason=reason)
            for instrument_id, reasons in failures.items()
            for position, (source, reason) in enumerate(reasons.items())
        )
        session.merge(AppSetting(key=REFRESHED_AT, value=refreshed_at.isoformat()))
        if succeeded:
            session.merge(AppSetting(key=SUCCEEDED_AT, value=refreshed_at.isoformat()))


def load_refresh(engine: Engine) -> tuple[datetime, dict[int, dict[str, str]]] | None:
    """The last refresh's time and its failures as saved by ``save_refresh``; ``None`` before the first refresh."""
    with Session(engine) as session:
        refreshed_at = session.get(AppSetting, REFRESHED_AT)
        if refreshed_at is None:
            return None
        failures: dict[int, dict[str, str]] = {}
        rows = session.scalars(
            select(PriceFailureRow).order_by(PriceFailureRow.instrument_id, PriceFailureRow.position)
        )
        for row in rows:
            failures.setdefault(row.instrument_id, {})[row.source] = row.reason
        return datetime.fromisoformat(refreshed_at.value), failures


def last_successful_refresh(engine: Engine) -> datetime | None:
    """The time of the last refresh saved as succeeded; ``None`` before the first."""
    succeeded_at = load_setting(engine, SUCCEEDED_AT)
    return None if succeeded_at is None else datetime.fromisoformat(succeeded_at)
