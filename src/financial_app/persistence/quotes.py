"""The Instruments' daily Quotes from the Price Sources (issue #30, spec 4.1).

One Quote per Instrument and day: a later fetch on the same day replaces it, and the newest is the current price.
Price history (Stage 4) fills older days into the same table.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from financial_app.domain.prices import Quote
from financial_app.persistence.models import QuoteRow


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
    """Each Instrument's newest Quote, by Instrument id."""
    with Session(engine) as session:
        newest = (
            select(QuoteRow.instrument_id, func.max(QuoteRow.day).label("day"))
            .group_by(QuoteRow.instrument_id)
            .subquery()
        )
        rows = session.scalars(
            select(QuoteRow).join(
                newest, (QuoteRow.instrument_id == newest.c.instrument_id) & (QuoteRow.day == newest.c.day)
            )
        )
        return {row.instrument_id: Quote(Decimal(row.price), row.currency, row.day, row.source) for row in rows}
