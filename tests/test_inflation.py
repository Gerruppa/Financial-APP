"""Inflation over a period from the GUS month-on-month CPI, spread evenly across each month's days as the sheet's
Benchmarki do, and the real return it gives (L-10, spec 3.4.1 and 6.1)."""

from datetime import date
from decimal import Decimal

from financial_app.domain.bonds import CpiReading
from financial_app.domain.inflation import inflation, real_return

READINGS = [
    CpiReading(2026, 1, Decimal("104.9"), Decimal("100.7")),
    CpiReading(2026, 2, Decimal("104.8"), Decimal("100.5")),
    CpiReading(2026, 3, Decimal("104.9"), Decimal("101.0")),
]


def _close(value: Decimal, expected: Decimal) -> bool:
    return abs(value - expected) < Decimal("1e-15")


def test_a_whole_month_inflates_by_its_month_on_month_index() -> None:
    # From the end of 31.01 to the end of 28.02: every day of February
    result = inflation(READINGS, date(2026, 1, 31), date(2026, 2, 28))

    assert result is not None
    assert _close(result.rate, Decimal("0.005"))
    assert result.complete and result.known_until == date(2026, 2, 28)


def test_part_of_a_month_compounds_its_share_of_the_days() -> None:
    # 14 of February's 28 days: the square root of the month's index
    result = inflation(READINGS, date(2026, 1, 31), date(2026, 2, 14))

    assert result is not None
    assert _close(result.rate, Decimal("1.005").sqrt() - 1)


def test_months_compound() -> None:
    result = inflation(READINGS, date(2026, 1, 31), date(2026, 3, 31))

    assert result is not None
    assert _close(result.rate, Decimal("1.005") * Decimal("1.01") - 1)


def test_a_month_gus_has_not_published_adds_no_inflation_and_marks_the_period_incomplete() -> None:
    # As the sheet: April has no reading yet, so the period's inflation stops at the end of March
    result = inflation(READINGS, date(2026, 2, 28), date(2026, 4, 20))

    assert result is not None
    assert _close(result.rate, Decimal("0.01"))
    assert not result.complete and result.known_until == date(2026, 3, 31)


def test_a_reading_without_a_month_on_month_index_counts_as_unpublished() -> None:
    readings = [*READINGS, CpiReading(2026, 4, Decimal("104.0"), None)]

    result = inflation(readings, date(2026, 3, 31), date(2026, 4, 30))

    assert result is None


def test_a_period_without_any_reading_has_no_inflation() -> None:
    assert inflation(READINGS, date(2026, 4, 1), date(2026, 5, 10)) is None
    assert inflation((), date(2026, 1, 31), date(2026, 2, 28)) is None


def test_a_single_day_period_has_no_days_to_inflate() -> None:
    # The "from" day is the base, so a period of one day covers none
    assert inflation(READINGS, date(2026, 2, 10), date(2026, 2, 10)) is None


def test_the_real_return_divides_out_the_inflation() -> None:
    assert real_return(Decimal("0.1"), Decimal("0.05")) == Decimal("1.1") / Decimal("1.05") - 1
    assert real_return(Decimal("0.02"), Decimal("0.02")) == 0
