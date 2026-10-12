"""Parity of the bond valuation with the Obligacje tab of the user's Inwestomat copy (L-3, spec 3.4.1, 9).

Each EDO row of the tab is valued by the MF issue letters with the rates the row lists (the first year's, then each
later year's) and compared with the sheet's value of one bond (its value over the number of bonds) within 0.01 PLN.
The sheet does not say on which day it computed its values, but in the first year it accrues linearly on the whole
amount, so each first-year row gives that day; the rows must agree on it. The other types follow in their slices.

The workbook is personal data: it stays in ``reference/`` (git-ignored), is read at test time, and the test is skipped
when it is missing. Nothing from the workbook is copied here.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from financial_app.domain.bond_valuation import Cpi, bond_value
from financial_app.domain.bonds import BondSeries, BondType, SeriesTerms, series_name

REFERENCE = Path(__file__).resolve().parents[1] / "reference" / "Newest portfolio.xlsx"
TOLERANCE = Decimal("0.01")
# The tab's columns: type, purchase day, first-year rate, margin, number of bonds, bought in a Rollover, amount paid,
# then a rate and a result per year, then the current value
TYPE, PURCHASED, FIRST_RATE, MARGIN, QUANTITY, ROLLOVER, PAID = range(7)
YEAR_RATES = slice(7, 31, 2)
VALUE = 31


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
        first year or for a Rollover purchase, which was paid less than its nominal."""
        if self.rollover:
            return None
        days = round((self.value / self.paid - 1) / self.rates[0] * 365)
        day = self.purchased + timedelta(days=days)
        return day if day < self.purchased.replace(year=self.purchased.year + 1) else None

    def series(self) -> BondSeries:
        name = series_name(self.bond_type, self.purchased)
        terms = SeriesTerms(
            name, "", self.purchased, self.purchased, Decimal(100), None, self.margin, self.rates, (None,)
        )
        return BondSeries(None, name, terms)


def read_bonds(path: Path) -> list[SheetBond]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        bonds = []
        for row in workbook["Obligacje"].iter_rows(min_row=3, values_only=True):
            bond_type, purchased = row[TYPE], row[PURCHASED]
            if not isinstance(bond_type, str) or bond_type not in set(BondType) or not isinstance(purchased, datetime):
                continue
            rates = tuple(Decimal(str(rate)) for rate in row[YEAR_RATES] if rate is not None)
            bonds.append(
                SheetBond(
                    BondType(bond_type),
                    purchased.date(),
                    rates,
                    Decimal(str(row[MARGIN] or 0)),
                    Decimal(str(row[QUANTITY])),
                    bool(row[ROLLOVER]),
                    Decimal(str(row[PAID])),
                    Decimal(str(row[VALUE])),
                )
            )
        return bonds
    finally:
        workbook.close()


@pytest.fixture(scope="module")
def bonds() -> list[SheetBond]:
    if not REFERENCE.exists():
        pytest.skip("Brak arkusza referencyjnego w reference/ – test porównawczy pominięty.")
    return [bond for bond in read_bonds(REFERENCE) if bond.bond_type is BondType.EDO]


@pytest.fixture(scope="module")
def sheet_day(bonds: list[SheetBond]) -> date:
    days = {day for bond in bonds if (day := bond.first_year_day()) is not None}
    assert len(days) == 1, f"Wiersze pierwszego roku dają różne dni wyceny: {sorted(days)}"
    return days.pop()


def test_each_edo_bond_is_worth_the_sheets_value_within_a_grosz(bonds: list[SheetBond], sheet_day: date) -> None:
    differences = []
    for bond in bonds:
        app = bond_value(bond.series(), bond.purchased, sheet_day, Cpi(()))
        sheet = bond.value / bond.quantity
        if app is None or abs(app.value - sheet) > TOLERANCE:
            differences.append(f"{bond.purchased} {bond.bond_type}: arkusz {sheet:.4f}, aplikacja {app}")
    assert bonds and not differences, "\n".join(differences)
