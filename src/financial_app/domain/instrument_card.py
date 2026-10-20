"""The header search (issue #175): Search Results grouped into one row per fund or company, and the Instrument Card's
figures."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from financial_app.domain.formatting import folded
from financial_app.domain.instrument_search import SearchResult
from financial_app.domain.instruments import Instrument
from financial_app.domain.periods import months_before
from financial_app.domain.prices import Quote

# How many of the user's own Instruments the header search lists
OWN_LIMIT = 5
# The Instrument Card's return periods, by label, in months back from the last close
RETURN_PERIODS = {"1M": 1, "3M": 3, "6M": 6, "1R": 12, "3L": 36}
# How many calendar years its returns table shows, this one first
RETURN_YEARS = 5
# The chart's periods in months back from the last close; YTD starts at the year's start, Max at the first close
CHART_PERIODS: dict[str, int | None] = {
    "YTD": None,
    "1M": 1,
    "3M": 3,
    "6M": 6,
    "1R": 12,
    "3L": 36,
    "5L": 60,
    "Max": None,
}


@dataclass(frozen=True)
class FoundInstrument:
    """The listings found of one fund or company, in the order found: those of one ISIN, or of one name when the
    search gives no ISIN (Yahoo gives one only to an ISIN searched for)."""

    name: str
    isin: str
    listings: list[SearchResult] = field(default_factory=list)

    @property
    def asset_classes(self) -> list[str]:
        """Each Asset Class name its listings belong to, once; none when their kind does not tell."""
        return list(dict.fromkeys(listing.asset_class for listing in self.listings if listing.asset_class))

    @property
    def sources(self) -> list[str]:
        """Each search service that found its listings, once."""
        return list(dict.fromkeys(listing.source for listing in self.listings if listing.source))


def group_results(results: Iterable[SearchResult]) -> list[FoundInstrument]:
    """``results`` as one FoundInstrument per ISIN, or per name for those without one, in the order first found."""
    found: dict[str, FoundInstrument] = {}
    for result in results:
        key = result.isin or f"name:{result.name.casefold()}"
        if key not in found:
            found[key] = FoundInstrument(result.name, result.isin)
        found[key].listings.append(result)
    return list(found.values())


def matching_instruments(instruments: Iterable[Instrument], query: str, limit: int = OWN_LIMIT) -> list[Instrument]:
    """The first ``limit`` of ``instruments`` whose name, ISIN or a Source Symbol contains ``query``, ignoring case and
    Polish letters; none for an empty query."""
    wanted = folded(query.strip())
    if not wanted:
        return []
    found = [instrument for instrument in instruments if any(wanted in folded(text) for text in _searched(instrument))]
    return found[:limit]


def _searched(instrument: Instrument) -> tuple[str, ...]:
    """The texts of an Instrument the header search looks in."""
    return (instrument.name, instrument.isin, *instrument.source_symbols.values())


def owned_instrument(listing: SearchResult, instruments: Sequence[Instrument]) -> Instrument | None:
    """The Instrument already holding ``listing``: one with any of its Source Symbols. The same ISIN on another
    exchange or in another currency is another listing, so another Instrument."""
    wanted = {(source, symbol.casefold()) for source, symbol in listing.source_symbols.items()}
    for instrument in instruments:
        if any((source, symbol.casefold()) in wanted for source, symbol in instrument.source_symbols.items()):
            return instrument
    return None


@dataclass(frozen=True)
class PriceSummary:
    """The Instrument Card's price panel: the last close ``price`` on ``day``, its change in percent from the close
    before it and from the last close of the year before (``None`` without one), and the lowest and highest close
    since the same day a year before."""

    price: Decimal
    currency: str
    day: date
    day_change_percent: Decimal | None
    ytd_percent: Decimal | None
    low_12m: Decimal
    high_12m: Decimal


def price_summary(quotes: Sequence[Quote]) -> PriceSummary | None:
    """The price panel of ``quotes`` (oldest first); ``None`` without any."""
    if not quotes:
        return None
    last = quotes[-1]
    year_ago = months_before(last.day, 12)
    closes = [quote.price for quote in quotes if quote.day >= year_ago]
    return PriceSummary(
        price=last.price,
        currency=last.currency,
        day=last.day,
        day_change_percent=_change(quotes[-2].price, last.price) if len(quotes) > 1 else None,
        ytd_percent=_change_since(quotes, date(last.day.year - 1, 12, 31), last.price),
        low_12m=min(closes),
        high_12m=max(closes),
    )


@dataclass(frozen=True)
class Returns:
    """The Instrument Card's returns in percent, from closes only (a distributing fund's then leave out its
    dividends): each of the last calendar ``years`` by year, this one so far first, and each of ``RETURN_PERIODS``
    up to the last close; ``None`` where the history starts later."""

    years: dict[int, Decimal | None]
    periods: dict[str, Decimal | None]


def returns(quotes: Sequence[Quote]) -> Returns:
    """The returns of ``quotes`` (oldest first); all ``None`` without any."""
    if not quotes:
        return Returns({}, dict.fromkeys(RETURN_PERIODS))
    last = quotes[-1]
    years: dict[int, Decimal | None] = {}
    for year in range(last.day.year, last.day.year - RETURN_YEARS, -1):
        closing = _close_on(quotes, date(year, 12, 31))
        years[year] = None if closing is None else _change_since(quotes, date(year - 1, 12, 31), closing)
    periods = {
        label: _change_since(quotes, months_before(last.day, months), last.price)
        for label, months in RETURN_PERIODS.items()
    }
    return Returns(years, periods)


def _close_on(quotes: Sequence[Quote], day: date) -> Decimal | None:
    """The last close on or before ``day``, ``None`` when the history starts after it."""
    found = [quote.price for quote in quotes if quote.day <= day]
    return found[-1] if found else None


def _change_since(quotes: Sequence[Quote], day: date, price: Decimal) -> Decimal | None:
    """``price``'s change in percent from the last close on or before ``day``, ``None`` without one."""
    base = _close_on(quotes, day)
    return None if base is None else _change(base, price)


def _change(base: Decimal, price: Decimal) -> Decimal:
    return (price / base - 1) * 100


def chart_window(quotes: Sequence[Quote], period: str) -> list[Quote]:
    """The closes of ``quotes`` (oldest first) the chart shows for ``period`` (a key of ``CHART_PERIODS``): from the
    last close on or before its start, which its returns count from, to the last one."""
    if not quotes or period == "Max":
        return list(quotes)
    last = quotes[-1].day
    months = CHART_PERIODS[period]
    start = date(last.year - 1, 12, 31) if months is None else months_before(last, months)
    base = max((quote.day for quote in quotes if quote.day <= start), default=quotes[0].day)
    return [quote for quote in quotes if quote.day >= base]
