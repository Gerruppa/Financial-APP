"""An Instrument's Quotes in a date range for History (Stage 4, ADR-0002, ADR-0006), the missing days fetched from
Yahoo, else Stooq."""

from collections.abc import Callable
from datetime import date, datetime

from sqlalchemy import Engine

from financial_app.domain.history import ONE_DAY, Cover, days_to_fetch, settled
from financial_app.domain.prices import HISTORY_SOURCES, STOOQ, YAHOO, PriceSourceError, Quote
from financial_app.persistence.history import quote_history_cover, quotes_between, save_quote_history
from financial_app.persistence.instruments import get_instrument
from financial_app.persistence.settings import STOOQ_API_KEY, load_setting
from financial_app.sources.stooq import StooqSource, fetch_from_stooq
from financial_app.sources.yahoo import YahooSource, fetch_from_yahoo


class QuoteHistory:
    """Quotes of an Instrument by day; ``fetch``, ``today`` and ``now`` are injectable so tests run without the
    network."""

    def __init__(
        self,
        engine: Engine,
        fetch: Callable[[str], str] = fetch_from_stooq,
        today: Callable[[], date] = date.today,
        now: Callable[[], datetime] = datetime.now,
        yahoo_fetch: Callable[[str], str | None] = fetch_from_yahoo,
    ) -> None:
        self.engine = engine
        self.fetch = fetch
        self.yahoo_fetch = yahoo_fetch
        self.today = today
        self.now = now

    def between(self, instrument_id: int, first: date, last: date) -> list[Quote]:
        """The Instrument's Quotes from ``first`` to ``last``, oldest first.

        Days not fetched yet are fetched once, from Yahoo when the Instrument has a Yahoo Source Symbol, else (or
        when Yahoo fails) from Stooq, and only up to yesterday: today's price is the price refresh's. They fill only
        days without a Quote. The last few days are asked for again until the source has a Quote on or after them
        (``domain.history.settled``). Without either symbol only the saved Quotes are given. When every source fails,
        the last ``PriceSourceError`` is raised and the days are tried again next time.
        """
        instrument = get_instrument(self.engine, instrument_id)
        sources = [(source, symbol) for source in HISTORY_SOURCES if (symbol := instrument.source_symbols.get(source))]
        if sources:
            today = self.today()
            cover = quote_history_cover(self.engine, instrument_id)
            for days in days_to_fetch(cover, first, min(last, today - ONE_DAY)):
                quotes = [
                    quote
                    for quote in self._history(sources, instrument.quote_currency, days)
                    if days.first <= quote.day <= days.last
                ]
                # Days before the cached ones are followed by Quotes, so they are all settled
                before_cover = cover is not None and days.last < cover.first
                newest = max((quote.day for quote in quotes), default=None)
                covered = days if before_cover else settled(days, newest, today)
                save_quote_history(self.engine, instrument_id, quotes, covered, self.now())
        return quotes_between(self.engine, instrument_id, first, last)

    def _history(self, sources: list[tuple[str, str]], currency: str, days: Cover) -> list[Quote]:
        error = PriceSourceError("Brak źródła historii notowań.")
        for source, symbol in sources:
            try:
                if source == YAHOO:
                    return YahooSource(self.yahoo_fetch).history(symbol, currency, days.first, days.last)
                assert source == STOOQ
                stooq = StooqSource(load_setting(self.engine, STOOQ_API_KEY) or "", self.fetch)
                return stooq.history(symbol, currency, days.first, days.last)
            except PriceSourceError as exc:
                error = exc
        raise error
