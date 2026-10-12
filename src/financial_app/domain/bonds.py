"""Polish retail treasury bonds (spec 3.4 and 3.4.1): the bond types, each Bond Series' terms from the MF file, GUS CPI
and the NBP reference rate, which the valuation of Stage 3 rests on.

Rates are fractions (0.0535 for 5.35%); CPI readings are GUS indices (103.4 when prices rose 3.4%).
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum


class BondType(StrEnum):
    """The retail treasury bond types the app values, by their MF code."""

    OTS = "OTS"
    ROR = "ROR"
    DOR = "DOR"
    TOS = "TOS"
    COI = "COI"
    EDO = "EDO"
    ROS = "ROS"
    ROD = "ROD"


# How long each type runs, in months from the purchase day
TERM_MONTHS = {
    BondType.OTS: 3,
    BondType.ROR: 12,
    BondType.DOR: 24,
    BondType.TOS: 36,
    BondType.COI: 48,
    BondType.EDO: 120,
    BondType.ROS: 72,
    BondType.ROD: 144,
}


# Interest periods of each type: a year, a month for ROR and DOR, the whole term for the fixed-rate OTS and TOS, as the
# MF file lists them
PERIODS = {
    BondType.OTS: 1,
    BondType.ROR: 12,
    BondType.DOR: 24,
    BondType.TOS: 1,
    BondType.COI: 4,
    BondType.EDO: 10,
    BondType.ROS: 6,
    BondType.ROD: 12,
}
# The fixed-rate types, with one rate for the whole term and no margin
FIXED_RATE_TYPES = frozenset({BondType.OTS, BondType.TOS})
# The types whose interest periods are months
MONTHLY_TYPES = frozenset({BondType.ROR, BondType.DOR})
# The family bonds, bought only with the 800+ benefit and never in a Rollover
FAMILY_TYPES = frozenset({BondType.ROS, BondType.ROD})
# The price of one bond bought in a Rollover when the MF file does not give it (spec 3.4)
DEFAULT_ROLLOVER_PRICE = Decimal("99.90")
ISSUE_PRICE = Decimal(100)
# The Asset Class a Bond Series is created in on its first purchase
TREASURY_BOND_CLASS = "Obligacje skarbowe polskie"
# A Bond Series' name: its type, then the month and year it matures, e.g. EDO1036
SERIES_NAME = re.compile(r"(OTS|ROR|DOR|TOS|COI|EDO|ROS|ROD)(\d{2})(\d{2})")


def bond_type_of(name: str) -> BondType | None:
    """The bond type of a Bond Series' name, or ``None`` when ``name`` is no Series."""
    match = SERIES_NAME.fullmatch(name)
    return BondType(match[1]) if match else None


def series_name(bond_type: BondType, purchase_day: date) -> str:
    """The Series a bond of ``bond_type`` bought on ``purchase_day`` belongs to: each month sells one Series of each
    type, named by the month and year it matures."""
    months = purchase_day.year * 12 + purchase_day.month - 1 + TERM_MONTHS[bond_type]
    return f"{bond_type}{months % 12 + 1:02}{months // 12 % 100:02}"


class BondDataError(Exception):
    """A bond data source (the MF file, GUS CPI, the NBP reference rate) gave nothing usable; the message is Polish."""


@dataclass(frozen=True)
class SeriesTerms:
    """One Bond Series as the MF file lists it.

    ``rates`` holds the rate of each interest period (a year, or a month for ROR and DOR) in order, ``None`` for a
    period MF has not published yet; ``interest`` the interest of one bond in PLN as the file gives it (per period for
    the coupon types, once for the others). ``rollover_price`` is ``None`` when the Series cannot be bought in a
    Rollover; ``margin`` is ``None`` for the fixed-rate types.
    """

    series: str
    isin: str
    sale_start: date
    sale_end: date
    issue_price: Decimal
    rollover_price: Decimal | None
    margin: Decimal | None
    rates: tuple[Decimal | None, ...]
    interest: tuple[Decimal | None, ...]

    @property
    def bond_type(self) -> BondType:
        return BondType(self.series[:3])


@dataclass(frozen=True)
class CpiReading:
    """GUS consumer price indices for a month: ``year_on_year`` against the same month a year before (bond rates) and
    ``month_on_month`` against the month before (real return); ``None`` where GUS gives none."""

    year: int
    month: int
    year_on_year: Decimal | None
    month_on_month: Decimal | None


@dataclass(frozen=True)
class ReferenceRate:
    """The NBP reference rate in force from ``valid_from`` (ROR and DOR rates follow it)."""

    valid_from: date
    rate: Decimal


@dataclass(frozen=True)
class RateCorrection:
    """The user's corrections of a Bond Series' rates: ``margin`` and the rate of each period (``rates`` in order), each
    ``None`` where the MF file's value stands."""

    margin: Decimal | None = None
    rates: tuple[Decimal | None, ...] = ()


@dataclass(frozen=True)
class BondSeries:
    """A Bond Series held as an Instrument (``instrument_id``, ``None`` before its first purchase), with its rates from
    the MF file (``mf``, ``None`` while the file does not list it) as the user corrected them (spec 3.4.1)."""

    instrument_id: int | None
    name: str
    mf: SeriesTerms | None
    correction: RateCorrection = field(default_factory=RateCorrection)

    @property
    def bond_type(self) -> BondType:
        bond_type = bond_type_of(self.name)
        assert bond_type is not None, self.name
        return bond_type

    @property
    def margin(self) -> Decimal | None:
        """The margin over CPI (or over the NBP reference rate for ROR and DOR); ``None`` for a fixed rate or while
        unknown."""
        if self.correction.margin is not None:
            return self.correction.margin
        return None if self.mf is None else self.mf.margin

    @property
    def margin_is_corrected(self) -> bool:
        return self.correction.margin is not None

    @property
    def rates(self) -> tuple[Decimal | None, ...]:
        """The rate of each interest period, ``None`` where neither MF nor the user has given one."""
        published = () if self.mf is None else self.mf.rates
        periods = max(PERIODS[self.bond_type], len(published))
        return tuple(self._rate(period, published) for period in range(periods))

    def _rate(self, period: int, published: tuple[Decimal | None, ...]) -> Decimal | None:
        corrected = self.correction.rates[period] if period < len(self.correction.rates) else None
        if corrected is not None:
            return corrected
        return published[period] if period < len(published) else None

    def is_corrected(self, period: int) -> bool:
        return period < len(self.correction.rates) and self.correction.rates[period] is not None

    @property
    def first_rate(self) -> Decimal | None:
        """The rate of the first period (the first year's for the yearly types)."""
        return self.rates[0]

    @property
    def rollover_price(self) -> Decimal | None:
        """The price of one bond bought in a Rollover; ``None`` for the family bonds, which no Rollover buys."""
        if self.bond_type in FAMILY_TYPES:
            return None
        if self.mf is not None:
            return self.mf.rollover_price
        return DEFAULT_ROLLOVER_PRICE


def correction_of(mf: SeriesTerms | None, margin: Decimal | None, rates: tuple[Decimal | None, ...]) -> RateCorrection:
    """The correction that gives a Series the ``margin`` and ``rates`` the user entered: only the values differing from
    the MF file's are kept, so a rate MF publishes later shows through. An empty value keeps the MF one."""
    published = () if mf is None else mf.rates
    kept = [
        rate if rate is not None and (period >= len(published) or rate != published[period]) else None
        for period, rate in enumerate(rates)
    ]
    while kept and kept[-1] is None:
        kept.pop()
    mf_margin = None if mf is None else mf.margin
    return RateCorrection(None if margin == mf_margin else margin, tuple(kept))
