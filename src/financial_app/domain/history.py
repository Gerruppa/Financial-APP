"""The days of a price or NBP Rate history already in the local cache, and which are still to be fetched (issue #33).

History (Stage 4, ADR-0002) asks for an Instrument's Quotes or a currency's NBP Rates in a date range. The days
already fetched are kept as one ``Cover``, so a range asked again is read from the cache and only the missing days
are fetched. Days without a Quote (weekends, holidays) are covered too, so they are never asked for twice.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Self

ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class Cover:
    """The days ``first`` to ``last``, both included."""

    first: date
    last: date

    @classmethod
    def of(cls, cover: Cover | None, first: date, last: date) -> Cover:
        """``cover`` grown by ``first`` to ``last``, or just those days when nothing was covered."""
        return cls(first, last) if cover is None else cover.extended_to(first, last)

    def extended_to(self, first: date, last: date) -> Self:
        return type(self)(min(self.first, first), max(self.last, last))

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
