"""Bonds listed on Catalyst: a price per bond from their percent of nominal (backlog L-23, spec 4).

Catalyst quotes a bond as a percent of its nominal, without the interest accrued since the last coupon (the clean
price), so one bond is worth that percent of its nominal plus the accrued interest, both per bond in PLN as
gpwcatalyst.pl lists them (today's, whatever the Quote's day). The treasury IZ bonds are indexed to inflation (L-24):
their nominal is 1000 zł times the indexation coefficient of the Quote's day that MF publishes on gov.pl with the
accrued interest.
"""

import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

IZ_SERIES = re.compile(r"IZ\d{4}")
IZ_BASE_NOMINAL = Decimal(1000)
GROSZ = Decimal("0.01")
# How long the last day of the gov.pl table stands in for a day it lacks; an older table is out of date
INDEXATION_STANDS_IN = timedelta(days=7)


@dataclass(frozen=True)
class BondFacts:
    """One bond's nominal and the interest accrued on it, in PLN."""

    nominal: Decimal
    accrued_interest: Decimal


class BondFactsSource(Protocol):
    """Where a Price Source quoting Catalyst finds each bond's facts; raises PriceSourceError without them."""

    def of(self, symbol: str, day: date) -> BondFacts: ...

    def new_refresh(self) -> None: ...


@dataclass(frozen=True)
class IndexationDay:
    """An IZ bond's indexation coefficient and accrued interest (PLN per bond) on ``day``, as MF publishes them."""

    day: date
    coefficient: Decimal
    accrued_interest: Decimal


def bond_price(percent: Decimal, facts: BondFacts) -> Decimal:
    """One bond's price in PLN: ``percent`` of its nominal (the Catalyst Quote) plus its accrued interest."""
    return percent * facts.nominal / 100 + facts.accrued_interest


def is_indexed(symbol: str) -> bool:
    """Whether ``symbol`` names an indexed treasury bond (IZ and its maturity, e.g. IZ0831)."""
    return IZ_SERIES.fullmatch(symbol.strip().upper()) is not None


def indexed_facts(days: Sequence[IndexationDay], on: date) -> BondFacts | None:
    """An IZ bond's facts on the day ``on``: the nominal 1000 zł times that day's coefficient, rounded to the grosz,
    and its accrued interest. The last day before ``on`` stands in when the table lacks it, up to a week; ``None`` when
    the table starts later or is older. ``days`` are in date order."""
    index = bisect_right([day.day for day in days], on)
    if not index or on - days[index - 1].day > INDEXATION_STANDS_IN:
        return None
    day = days[index - 1]
    nominal = (day.coefficient * IZ_BASE_NOMINAL).quantize(GROSZ, ROUND_HALF_UP)
    return BondFacts(nominal, day.accrued_interest)
