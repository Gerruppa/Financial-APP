"""The Instrument Card's price history (issue #175): a listing's whole history fetched live from Yahoo, else
analizy.pl (funds and PPK), for its chart and returns. Nothing is saved, so a Search Result leaves no trace."""

from collections.abc import Callable, Mapping
from datetime import date

from financial_app.domain.prices import ANALIZY, YAHOO, PriceSourceError, Quote
from financial_app.sources.analizy import AnalizySource, fetch_from_analizy
from financial_app.sources.yahoo import YahooSource, fetch_from_yahoo

# Before any listing's first close, so the history asked for is the whole of it
FIRST_DAY = date(1970, 1, 2)


class CardHistory:
    """Closes by Source Symbols; ``yahoo_fetch`` and ``analizy_fetch`` are injectable so tests run on saved
    responses."""

    def __init__(
        self,
        yahoo_fetch: Callable[[str], str | None] = fetch_from_yahoo,
        analizy_fetch: Callable[[str], str | None] = fetch_from_analizy,
    ) -> None:
        self.yahoo = YahooSource(yahoo_fetch)
        self.analizy = AnalizySource(analizy_fetch)

    def of(self, source_symbols: Mapping[str, str], currency: str, last: date) -> list[Quote]:
        """The closes in ``currency`` up to ``last``, oldest first, from the Yahoo symbol, else the analizy.pl Fund
        Code; none without either. Raises ``PriceSourceError`` (Polish) when the source fails."""
        symbols = {source: symbol.strip() for source, symbol in source_symbols.items() if symbol.strip()}
        source = next((source for source in (YAHOO, ANALIZY) if source in symbols), None)
        if source is None:
            return []
        if not currency:
            raise PriceSourceError(
                "Nie wiadomo, w jakiej walucie jest wyceniany, więc nie można pokazać jego historii."
            )
        price_source = self.yahoo if source == YAHOO else self.analizy
        return price_source.history(symbols[source], currency, FIRST_DAY, last)
