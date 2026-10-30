"""The interest periods of a Bond Series as the bond help window lists them (issue #272): each period's dates, its rate
as the valuation takes it (``bond_valuation.period_rate``) and where that rate comes from.

A capitalised type is listed by year (TOS too, compounding its one fixed rate yearly), a coupon type by its coupon
period (a year for COI, a month for ROR and DOR), and the three-month OTS as one period to maturity.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_app.domain.bond_valuation import Cpi, ReferenceRates, period_months, period_rate
from financial_app.domain.bonds import FIXED_RATE_TYPES, TERM_MONTHS, BondSeries, add_months

# Where a period's rate comes from, besides the labels of an estimated rate (``RateLabel``)
FROM_MF = "z pliku MF"
CORRECTED = "poprawione ręcznie"
NO_DATA = "brak danych"


@dataclass(frozen=True)
class GuidePeriod:
    """Interest period ``number`` (from 1), from ``start`` to ``end``, at ``rate`` (a fraction; ``None`` while
    unknown), with ``source`` saying where the rate comes from, in Polish."""

    number: int
    start: date
    end: date
    rate: Decimal | None
    source: str


def guide_periods(
    series: BondSeries, purchase_day: date, cpi: Cpi, reference: ReferenceRates
) -> tuple[GuidePeriod, ...]:
    """Every interest period of a bond of ``series`` bought on ``purchase_day``, oldest first."""
    bond_type = series.bond_type
    # A period longer than a year (TOS) still compounds yearly
    months = min(period_months(bond_type), 12)
    periods = []
    for period in range(TERM_MONTHS[bond_type] // months):
        start = add_months(purchase_day, months * period)
        rate = period_rate(series, period, start, cpi, reference)
        # A fixed rate is the first period's every year
        corrected = series.is_corrected(0 if bond_type in FIXED_RATE_TYPES else period)
        if rate is None:
            source = NO_DATA
        elif rate.label is not None:
            source = str(rate.label)
        else:
            source = CORRECTED if corrected else FROM_MF
        end = add_months(purchase_day, months * (period + 1))
        periods.append(GuidePeriod(period + 1, start, end, None if rate is None else rate.rate, source))
    return tuple(periods)
