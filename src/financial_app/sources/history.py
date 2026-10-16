"""An Instrument's Quotes in a date range for History (Stage 4, ADR-0002, ADR-0006), the missing days fetched from
Yahoo, else analizy.pl (funds and PPK, #101), else Stooq."""

from collections.abc import Callable
from datetime import date, datetime

from sqlalchemy import Engine

from financial_app.domain.history import ONE_DAY, Cover, days_to_fetch, settled
from financial_app.domain.prices import ANALIZY, HISTORY_SOURCES, STOOQ, YAHOO, PriceSourceError, Quote
from financial_app.persistence.history import quote_history_cover, quotes_between, save_quote_history
from financial_app.persistence.instruments import get_instrument
from financial_app.persistence.settings import STOOQ_API_KEY, load_setting
from financial_app.sources.analizy import AnalizySource, fetch_from_analizy
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
        analizy_fetch: Callable[[str], str | None] = fetch_from_analizy,
    ) -> None:
        self.engine = engine
        self.fetch = fetch
        self.yahoo_fetch = yahoo_fetch
        self.analizy_fetch = analizy_fetch
        self.today = today
        self.now = now

    def between(self, instrument_id: int, first: date, last: date) -> list[Quote]:
        """The Instrument's Quotes from ``first`` to ``last``, oldest first.

        Days not fetched yet are fetched once, from the first of Yahoo, analizy.pl (its Fund Code) and Stooq the
        Instrument has a Source Symbol for that gives them, and only up to yesterday: today's price is the price
        refresh's. They fill only days without a Quote. The last few days are asked for again until the source has a
        Quote on or after them (``domain.history.settled``). Without any of those symbols only the saved Quotes are
        given. A source answering with no Quotes leaves the days to the next one. When every source fails, the last
        ``PriceSourceError`` is raised and the days are tried again next time.
        """
        instrument = get_instrument(self.engine, instrument_id)
        # analizy.pl answers with the whole series, so one request serves every range of this call
        analizy = AnalizySource(_once(self.analizy_fetch))
        sources = [(source, symbol) for source in HISTORY_SOURCES if (symbol := instrument.source_symbols.get(source))]
        if sources:
            today = self.today()
            cover = quote_history_cover(self.engine, instrument_id)
            for days in days_to_fetch(cover, first, min(last, today - ONE_DAY)):
                quotes = [
                    quote
                    for quote in self._history(sources, instrument.quote_currency, days, analizy)
                    if days.first <= quote.day <= days.last
                ]
                # Days before the cached ones are followed by Quotes, so they are all settled
                before_cover = cover is not None and days.last < cover.first
                newest = max((quote.day for quote in quotes), default=None)
                covered = days if before_cover else settled(days, newest, today)
                save_quote_history(self.engine, instrument_id, quotes, covered, self.now())
        return quotes_between(self.engine, instrument_id, first, last)

    def _history(
        self, sources: list[tuple[str, str]], currency: str, days: Cover, analizy: AnalizySource
    ) -> list[Quote]:
        error = PriceSourceError("Brak źródła historii notowań.")
        answered = False  # a source gave no Quotes for the days, without failing
        for source, symbol in sources:
            try:
                if source == YAHOO:
                    quotes = YahooSource(self.yahoo_fetch).history(symbol, currency, days.first, days.last)
                elif source == ANALIZY:
                    quotes = analizy.history(symbol, currency, days.first, days.last)
                else:
                    assert source == STOOQ
                    stooq = StooqSource(load_setting(self.engine, STOOQ_API_KEY) or "", self.fetch)
                    quotes = stooq.history(symbol, currency, days.first, days.last)
            except PriceSourceError as exc:
                error = exc
                continue
            if quotes:
                return quotes
            answered = True
        if answered:
            return []
        raise error


def _once(fetch: Callable[[str], str | None]) -> Callable[[str], str | None]:
    """``fetch`` asking each URL only once."""
    answers: dict[str, str | None] = {}

    def fetch_once(url: str) -> str | None:
        if url not in answers:
            answers[url] = fetch(url)
        return answers[url]

    return fetch_once
