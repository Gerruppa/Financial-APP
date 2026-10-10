"""Price and NBP Rate history in the local cache, with the days already fetched (issue #33, ADR-0002).

Fetched Quotes go into the same daily Quotes table as the current prices (spec 4.1); NBP Rates by the day they were
published go into their own table, apart from the NBP Rates (D-1) cached by Transaction day.
"""

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from financial_app.domain.currencies import NbpRate
from financial_app.domain.history import Cover
from financial_app.domain.prices import STOOQ, Quote
from financial_app.persistence.models import NbpHistoryRow, NbpRateHistoryRow, QuoteHistoryRow, QuoteRow


def quote_history_cover(engine: Engine, instrument_id: int) -> Cover | None:
    """The days whose Quotes of the Instrument were fetched from Stooq, if any."""
    with Session(engine) as session:
        return _cover(session.get(QuoteHistoryRow, instrument_id))


def save_quote_history(
    engine: Engine, instrument_id: int, quotes: Iterable[Quote], fetched: Cover | None, fetched_at: datetime
) -> None:
    """Save the fetched Quotes for days without a Quote yet (the price refresh's stay, spec 4.1) and add the days
    ``fetched``, if any, to the Instrument's cover, all or nothing."""
    with Session(engine) as session, session.begin():
        days = set(session.scalars(select(QuoteRow.day).where(QuoteRow.instrument_id == instrument_id)))
        session.add_all(
            QuoteRow(
                instrument_id=instrument_id,
                day=quote.day,
                price=str(quote.price),
                currency=quote.currency,
                source=quote.source,
                fetched_at=fetched_at,
            )
            for quote in quotes
            if quote.day not in days
        )
        if fetched is not None:
            cover = fetched.joined(_cover(session.get(QuoteHistoryRow, instrument_id)))
            session.merge(QuoteHistoryRow(instrument_id=instrument_id, first_day=cover.first, last_day=cover.last))


def forget_quote_history(session: Session, instrument_id: int) -> None:
    """Drop what was fetched from Stooq for the Instrument, e.g. when its Stooq Source Symbol changes."""
    session.execute(delete(QuoteHistoryRow).where(QuoteHistoryRow.instrument_id == instrument_id))
    session.execute(delete(QuoteRow).where((QuoteRow.instrument_id == instrument_id) & (QuoteRow.source == STOOQ)))


def quotes_between(engine: Engine, instrument_id: int, first: date, last: date) -> list[Quote]:
    """The Instrument's saved Quotes from ``first`` to ``last``, oldest first."""
    with Session(engine) as session:
        rows = session.scalars(
            select(QuoteRow)
            .where(QuoteRow.instrument_id == instrument_id, QuoteRow.day.between(first, last))
            .order_by(QuoteRow.day)
        )
        return [Quote(Decimal(row.price), row.currency, row.day, row.source) for row in rows]


def nbp_history_cover(engine: Engine, currency: str) -> Cover | None:
    """The days whose NBP Rates of ``currency`` were fetched, if any."""
    with Session(engine) as session:
        return _cover(session.get(NbpHistoryRow, currency))


def save_nbp_history(engine: Engine, currency: str, rates: Iterable[NbpRate], fetched: Cover) -> None:
    """Save the NBP Rates published in the days ``fetched`` and add the days to the currency's cover."""
    with Session(engine) as session, session.begin():
        for rate in rates:
            session.merge(
                NbpRateHistoryRow(currency=currency, day=rate.published_on, rate=str(rate.rate), table=rate.table)
            )
        cover = fetched.joined(_cover(session.get(NbpHistoryRow, currency)))
        session.merge(NbpHistoryRow(currency=currency, first_day=cover.first, last_day=cover.last))


def nbp_rates_between(engine: Engine, currency: str, first: date, last: date) -> list[NbpRate]:
    """The NBP Rates of ``currency`` published from ``first`` to ``last``, oldest first."""
    with Session(engine) as session:
        rows = session.scalars(
            select(NbpRateHistoryRow)
            .where(NbpRateHistoryRow.currency == currency, NbpRateHistoryRow.day.between(first, last))
            .order_by(NbpRateHistoryRow.day)
        )
        return [NbpRate(row.currency, Decimal(row.rate), row.day, row.table) for row in rows]


def _cover(row: QuoteHistoryRow | NbpHistoryRow | None) -> Cover | None:
    return None if row is None else Cover(row.first_day, row.last_day)
