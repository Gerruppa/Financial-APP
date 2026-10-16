"""The MF Series a past purchase may pick and their sale windows (L-26, spec 3.4.1)."""

from datetime import date
from decimal import Decimal

from financial_app.domain.bonds import BondType, SeriesTerms, series_of_type, sold_on


def _terms(series: str, first: date, last: date) -> SeriesTerms:
    return SeriesTerms(series, "PL0", first, last, Decimal(100), Decimal("99.9"), None, (), ())


EDO0827 = _terms("EDO0827", date(2017, 8, 1), date(2017, 8, 31))
EDO1036 = _terms("EDO1036", date(2026, 10, 1), date(2026, 10, 31))
COI1130 = _terms("COI1130", date(2026, 11, 1), date(2026, 11, 30))


def test_the_types_series_come_newest_sold_first() -> None:
    assert series_of_type([EDO0827, COI1130, EDO1036], BondType.EDO) == [EDO1036, EDO0827]


def test_a_purchase_is_within_the_sale_window_inclusive() -> None:
    assert sold_on(EDO0827, date(2017, 8, 1), rollover=False)
    assert sold_on(EDO0827, date(2017, 8, 31), rollover=False)
    assert not sold_on(EDO0827, date(2017, 7, 31), rollover=False)
    assert not sold_on(EDO0827, date(2017, 9, 1), rollover=False)


def test_a_rollover_may_fall_a_week_after_the_sale() -> None:
    assert sold_on(EDO0827, date(2017, 9, 7), rollover=True)
    assert not sold_on(EDO0827, date(2017, 9, 8), rollover=True)
    assert not sold_on(EDO0827, date(2017, 7, 31), rollover=True)
