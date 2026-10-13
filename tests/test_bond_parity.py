"""Parity of the bond valuation with the Obligacje tab of the user's Inwestomat copy (L-3, L-11, spec 3.4.1, 9).

The sheet values EDO, ROS, ROD and COI with one set of yearly formulas and TOS with its own price formula; it has no
OTS, ROR or DOR. Two checks:

- Each row of the user's tab, whatever its type, is valued by the MF issue letters with the rates the row lists (the
  first year's, then each later year's) and compared with the sheet's value of one bond within 0.01 PLN. The sheet
  does not say on which day it computed its values, but in the first year it accrues linearly on the whole amount, so
  each first-year row gives that day; the rows must agree on it.
- The types the user holds no row of are compared with ``sheet_value``, the tab's formulas re-stated (yearly linear
  accrual chained over the years on the whole amount, a COI year on the nominal, a TOS per bond rounded to the grosz),
  on every 10th day from the purchase past the maturity: their values differ only by the app's rounding of one bond
  (section 9, item 18). The sheet's TOS keeps accruing after its maturity (item 19), so a TOS is compared up to it.

The workbook is personal data: it stays in ``reference/`` (git-ignored), is read at test time, and that check is
skipped when it is missing. Nothing from the workbook is copied here.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from financial_app.domain.bond_valuation import Cpi, bond_value
from financial_app.domain.bonds import (
    ISSUE_PRICE,
    TERM_MONTHS,
    BondSeries,
    BondType,
    SeriesTerms,
    add_months,
    maturity,
    series_name,
)

REFERENCE = Path(__file__).resolve().parents[1] / "reference" / "Newest portfolio.xlsx"
TOLERANCE = Decimal("0.01")
# The tab's columns: type, purchase day, first-year rate, margin, number of bonds, bought in a Rollover, amount paid,
# then a rate and a result per year, then the current value; a TOS has only its price of one bond
TYPE, PURCHASED, FIRST_RATE, MARGIN, QUANTITY, ROLLOVER, PAID = range(7)
YEAR_RATES = slice(7, 31, 2)
VALUE = 31
TOS_PRICE = 37
# The types the sheet values
SHEET_TYPES = (BondType.EDO, BondType.ROS, BondType.ROD, BondType.COI, BondType.TOS)


@dataclass(frozen=True)
class SheetBond:
    """One row of the Obligacje tab."""

    bond_type: BondType
    purchased: date
    rates: tuple[Decimal, ...]
    margin: Decimal
    quantity: Decimal
    rollover: bool
    paid: Decimal
    value: Decimal

    def first_year_day(self) -> date | None:
        """The day the sheet's linear first-year accrual on the whole amount gives the row's value; ``None`` past the
        first year, for a Rollover purchase, which was paid less than its nominal, and for a TOS, whose value is
        rounded per bond."""
        if self.rollover or self.bond_type is BondType.TOS:
            return None
        days = round((self.value / self.paid - 1) / self.rates[0] * 365)
        day = self.purchased + timedelta(days=days)
        return day if day < self.purchased.replace(year=self.purchased.year + 1) else None

    def series(self) -> BondSeries:
        return _series(self.bond_type, self.purchased, self.margin, self.rates)


def _series(bond_type: BondType, purchased: date, margin: Decimal, rates: tuple[Decimal, ...]) -> BondSeries:
    name = series_name(bond_type, purchased)
    terms = SeriesTerms(name, "", purchased, purchased, ISSUE_PRICE, None, margin, rates, (None,))
    return BondSeries(None, name, terms)


def read_bonds(path: Path) -> list[SheetBond]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        bonds = []
        for row in workbook["Obligacje"].iter_rows(min_row=3, values_only=True):
            bond_type, purchased = row[TYPE], row[PURCHASED]
            if not isinstance(bond_type, str) or bond_type not in SHEET_TYPES or not isinstance(purchased, datetime):
                continue
            kind = BondType(bond_type)
            quantity = Decimal(str(row[QUANTITY]))
            if kind is BondType.TOS:
                rates: tuple[Decimal, ...] = (Decimal(str(row[FIRST_RATE])),)
                value = Decimal(str(row[TOS_PRICE])) * quantity
            else:
                rates = tuple(Decimal(str(rate)) for rate in row[YEAR_RATES] if rate is not None)
                value = Decimal(str(row[VALUE]))
            bonds.append(
                SheetBond(
                    kind,
                    purchased.date(),
                    rates,
                    Decimal(str(row[MARGIN] or 0)),
                    quantity,
                    bool(row[ROLLOVER]),
                    Decimal(str(row[PAID])),
                    value,
                )
            )
        return bonds
    finally:
        workbook.close()


@pytest.fixture(scope="module")
def bonds() -> list[SheetBond]:
    if not REFERENCE.exists():
        pytest.skip("Brak arkusza referencyjnego w reference/ – test porównawczy pominięty.")
    return read_bonds(REFERENCE)


@pytest.fixture(scope="module")
def sheet_day(bonds: list[SheetBond]) -> date:
    days = {day for bond in bonds if (day := bond.first_year_day()) is not None}
    assert len(days) == 1, f"Wiersze pierwszego roku dają różne dni wyceny: {sorted(days)}"
    return days.pop()


def test_each_bond_of_the_sheet_is_worth_its_value_within_a_grosz(bonds: list[SheetBond], sheet_day: date) -> None:
    differences = []
    for bond in bonds:
        app = bond_value(bond.series(), bond.purchased, sheet_day, Cpi(()))
        sheet = bond.value / bond.quantity
        if app is None or abs(app.value - sheet) > TOLERANCE:
            differences.append(f"{bond.purchased} {bond.bond_type}: arkusz {sheet:.4f}, aplikacja {app}")
    assert bonds and not differences, "\n".join(differences)


def sheet_value(bond_type: BondType, purchased: date, rates: tuple[Decimal, ...], day: date) -> Decimal:
    """One bond as the Obligacje tab values it at the end of ``day`` (its formulas re-stated, not its data)."""
    if bond_type is BondType.TOS:
        return _sheet_tos(purchased, rates[0], day)
    if bond_type is BondType.COI:
        # The year the day is in (the last after maturity), accrued on the nominal
        year = min(_whole_years(purchased, day), _term_years(bond_type) - 1)
        return ISSUE_PRICE * (1 + _year_share(purchased, year, day) * rates[year])
    value = ISSUE_PRICE
    for year in range(_term_years(bond_type)):
        value *= 1 + _year_share(purchased, year, day) * rates[year]
    return value


def _term_years(bond_type: BondType) -> int:
    return TERM_MONTHS[bond_type] // 12


def _year_share(purchased: date, year: int, day: date) -> Decimal:
    """The share of the bond's year ``year`` (from 0) gone by ``day``, between 0 and 1."""
    start, end = add_months(purchased, 12 * year), add_months(purchased, 12 * (year + 1))
    return Decimal(0) if start > day else min(Decimal((day - start).days) / (end - start).days, Decimal(1))


def _whole_years(purchased: date, day: date) -> int:
    """DATEDIF(purchased; day; "Y")."""
    years = 0
    while add_months(purchased, 12 * (years + 1)) <= day:
        years += 1
    return years


def _sheet_tos(purchased: date, rate: Decimal, day: date) -> Decimal:
    """The tab's TOS price: linear within each year on the year's starting value, rounded to the grosz."""
    ends = [add_months(purchased, 12 * year) for year in range(4)]
    value = ISSUE_PRICE
    for year in range(3):
        if day < ends[year + 1] or year == 2:
            value = value * (1 + rate * (day - ends[year]).days / (ends[year + 1] - ends[year]).days)
            break
        value *= 1 + rate
    return value.quantize(Decimal("0.01"))


# A first-year rate, then later years' rates as MF would publish them (CPI + margin)
RATES = (Decimal("0.068"), Decimal("0.0745"), Decimal("0.0412"), Decimal("0.035"), Decimal("0.029"), Decimal("0.031"))


@pytest.mark.parametrize("bond_type", SHEET_TYPES)
@pytest.mark.parametrize("purchased", [date(2023, 3, 14), date(2024, 1, 31)])
def test_each_type_the_sheet_values_follows_its_formulas_within_a_grosz(bond_type: BondType, purchased: date) -> None:
    years = _term_years(bond_type)
    rates = tuple(RATES[min(year, len(RATES) - 1)] for year in range(max(years, 1)))
    series = _series(bond_type, purchased, Decimal("0.015"), rates)
    end = maturity(bond_type, purchased) + (timedelta(0) if bond_type is BondType.TOS else timedelta(days=40))
    differences = []
    day = purchased
    while day <= end:
        app = bond_value(series, purchased, day, Cpi(()))
        sheet = sheet_value(bond_type, purchased, rates, day)
        if app is None or abs(app.value - sheet) > TOLERANCE:
            differences.append(f"{day}: arkusz {sheet:.4f}, aplikacja {app}")
        day += timedelta(days=10)
    assert not differences, "\n".join(differences)
