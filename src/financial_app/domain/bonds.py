"""Polish retail treasury bonds (spec 3.4 and 3.4.1): the bond types, each Bond Series' terms from the MF file, GUS CPI
and the NBP reference rate, which the valuation of Stage 3 rests on.

Rates are fractions (0.0535 for 5.35%); CPI readings are GUS indices (103.4 when prices rose 3.4%).
"""

from dataclasses import dataclass
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
