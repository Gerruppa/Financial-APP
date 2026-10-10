"""An Instrument's Quotes in a date range for History (Stage 4, ADR-0002), the missing days fetched from Stooq."""

from collections.abc import Callable
from datetime import date, datetime

from sqlalchemy import Engine

from financial_app.domain.history import ONE_DAY, days_to_fetch, settled
from financial_app.domain.prices import STOOQ, Quote
from financial_app.persistence.history import quote_history_cover, quotes_between, save_quote_history
from financial_app.persistence.instruments import get_instrument
from financial_app.persistence.settings import STOOQ_API_KEY, load_setting
from financial_app.sources.stooq import StooqSource, fetch_from_stooq


class QuoteHistory:
    """Quotes of an Instrument by day; ``fetch``, ``today`` and ``now`` are injectable so tests run without the
    network."""

    def __init__(
        self,
        engine: Engine,
        fetch: Callable[[str], str] = fetch_from_stooq,
        today: Callable[[], date] = date.today,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.engine = engine
        self.fetch = fetch
        self.today = today
        self.now = now

    def between(self, instrument_id: int, first: date, last: date) -> list[Quote]:
        """The Instrument's Quotes from ``first`` to ``last``, oldest first.

        Days not fetched yet are fetched from Stooq once, when the Instrument has a Stooq Source Symbol, and only up
        to yesterday: today's price is the price refresh's. They fill only days without a Quote. The last few days
        are asked for again until Stooq has a Quote on or after them (``domain.history.settled``). Without the symbol
        only the saved Quotes are given. A failed fetch raises ``PriceSourceError`` and is tried again next time.
        """
        instrument = get_instrument(self.engine, instrument_id)
        if (symbol := instrument.source_symbols.get(STOOQ)) is not None:
            today = self.today()
            cover = quote_history_cover(self.engine, instrument_id)
            missing = days_to_fetch(cover, first, min(last, today - ONE_DAY))
            stooq = StooqSource(load_setting(self.engine, STOOQ_API_KEY) or "", self.fetch)
            for days in missing:
                quotes = [
                    quote
                    for quote in stooq.history(symbol, instrument.quote_currency, days.first, days.last)
                    if days.first <= quote.day <= days.last
                ]
                # Days before the cached ones are followed by Quotes, so they are all settled
                before_cover = cover is not None and days.last < cover.first
                newest = max((quote.day for quote in quotes), default=None)
                covered = days if before_cover else settled(days, newest, today)
                save_quote_history(self.engine, instrument_id, quotes, covered, self.now())
        return quotes_between(self.engine, instrument_id, first, last)
