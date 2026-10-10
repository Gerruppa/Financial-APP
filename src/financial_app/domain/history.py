"""The days of a price or NBP Rate history already in the local cache, and which are still to be fetched (issue #33).

History (Stage 4, ADR-0002) asks for an Instrument's Quotes or a currency's NBP Rates in a date range. The days
already fetched are kept as one ``Cover``, so a range asked again is read from the cache and only the missing days
are fetched. Days without a Quote (weekends, holidays) are covered too, so they are never asked for twice.
"""

from dataclasses import dataclass
from datetime import date, timedelta

ONE_DAY = timedelta(days=1)
# A source may publish a day's prices late, and a weekend or a holiday has none: the last days without a Quote are
# not taken as fetched yet
UNSETTLED_DAYS = 3


@dataclass(frozen=True)
class Cover:
    """The days ``first`` to ``last``, both included."""

    first: date
    last: date

    def joined(self, cover: Cover | None) -> Cover:
        """These days together with ``cover`` (adjacent or overlapping), or just these when nothing was covered."""
        return self if cover is None else Cover(min(self.first, cover.first), max(self.last, cover.last))

    def split(self, days: int) -> list[Cover]:
        """The same days in consecutive pieces of at most ``days`` days, for sources limiting a request's range."""
        pieces, start = [], self.first
        while start <= self.last:
            end = min(start + timedelta(days=days - 1), self.last)
            pieces.append(Cover(start, end))
            start = end + ONE_DAY
        return pieces


def days_to_fetch(cover: Cover | None, first: date, last: date) -> list[Cover]:
    """The days to fetch so that ``first`` to ``last`` is cached, given the days ``cover`` already is.

    A range apart from the cached days also takes the gap between them, so the cached days stay one ``Cover``.
    """
    if first > last:
        return []
    if cover is None:
        return [Cover(first, last)]
    missing = []
    if first < cover.first:
        missing.append(Cover(first, cover.first - ONE_DAY))
    if last > cover.last:
        missing.append(Cover(cover.last + ONE_DAY, last))
    return missing


def settled(fetched: Cover, newest: date | None, today: date) -> Cover | None:
    """The part of the days ``fetched`` (whose newest Quote is from ``newest``) that need not be asked for again.

    Of the last ``UNSETTLED_DAYS`` days before ``today`` only those up to the newest Quote are; ``None`` when no day
    is.
    """
    recent = today - timedelta(days=UNSETTLED_DAYS)
    if fetched.last < recent:
        return fetched
    last = min(fetched.last, max(newest or date.min, recent - ONE_DAY))
    return Cover(fetched.first, last) if last >= fetched.first else None
