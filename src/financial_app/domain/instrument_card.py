"""The Instrument Card's figures (issue #175): its price panel, returns and the chart's closes for each period."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from financial_app.domain.periods import months_before
from financial_app.domain.prices import Quote


class CardPeriod(StrEnum):
    """A period of the card's chart or returns, by its short label; it runs from its ``start`` to the last close.

    Not ``domain.periods.PeriodPreset``: the card has 6M and Max, which the period selector has not, and counts back
    from the last close, not today."""

    YEAR_TO_DATE = "YTD"
    ONE_MONTH = "1M"
    THREE_MONTHS = "3M"
    SIX_MONTHS = "6M"
    ONE_YEAR = "1R"
    THREE_YEARS = "3L"
    FIVE_YEARS = "5L"
    MAX = "Max"

    @property
    def name_pl(self) -> str:
        """Its full Polish name, e.g. "3 miesiące"."""
        return _NAMES[self]

    def start(self, last: date) -> date | None:
        """The day its return counts from, by the ``last`` close: the same day its months earlier, the last day of
        the year before for YTD, ``None`` (the first close) for Max."""
        if self is CardPeriod.MAX:
            return None
        if self is CardPeriod.YEAR_TO_DATE:
            return date(last.year - 1, 12, 31)
        return months_before(last, _MONTHS_BACK[self])


_NAMES = {
    CardPeriod.YEAR_TO_DATE: "Od początku roku",
    CardPeriod.ONE_MONTH: "1 miesiąc",
    CardPeriod.THREE_MONTHS: "3 miesiące",
    CardPeriod.SIX_MONTHS: "6 miesięcy",
    CardPeriod.ONE_YEAR: "1 rok",
    CardPeriod.THREE_YEARS: "3 lata",
    CardPeriod.FIVE_YEARS: "5 lat",
    CardPeriod.MAX: "Cała historia",
}
_MONTHS_BACK = {
    CardPeriod.ONE_MONTH: 1,
    CardPeriod.THREE_MONTHS: 3,
    CardPeriod.SIX_MONTHS: 6,
    CardPeriod.ONE_YEAR: 12,
    CardPeriod.THREE_YEARS: 36,
    CardPeriod.FIVE_YEARS: 60,
}
# The returns table's periods
RETURN_PERIODS = (
    CardPeriod.ONE_MONTH,
    CardPeriod.THREE_MONTHS,
    CardPeriod.SIX_MONTHS,
    CardPeriod.ONE_YEAR,
    CardPeriod.THREE_YEARS,
)
# How many calendar years the returns table shows, this one first
RETURN_YEARS = 5


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
    periods: dict[CardPeriod, Decimal | None]


def returns(quotes: Sequence[Quote]) -> Returns:
    """The returns of ``quotes`` (oldest first); all ``None`` without any."""
    if not quotes:
        return Returns({}, dict.fromkeys(RETURN_PERIODS))
    last = quotes[-1]
    years: dict[int, Decimal | None] = {}
    for year in range(last.day.year, last.day.year - RETURN_YEARS, -1):
        closing = _close_on(quotes, date(year, 12, 31))
        years[year] = None if closing is None else _change_since(quotes, date(year - 1, 12, 31), closing)
    periods: dict[CardPeriod, Decimal | None] = {}
    for period in RETURN_PERIODS:
        start = period.start(last.day)
        assert start is not None  # only Max has none
        periods[period] = _change_since(quotes, start, last.price)
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


def chart_window(quotes: Sequence[Quote], period: CardPeriod) -> list[Quote]:
    """The closes of ``quotes`` (oldest first) the chart shows for ``period``: from the last close on or before its
    start, which its return counts from, to the last one."""
    start = period.start(quotes[-1].day) if quotes else None
    if start is None:
        return list(quotes)
    base = max((quote.day for quote in quotes if quote.day <= start), default=quotes[0].day)
    return [quote for quote in quotes if quote.day >= base]
