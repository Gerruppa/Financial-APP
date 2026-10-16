"""Bond Series and their rates (L-2, spec 3.4.1): the Series a purchase buys, and the MF rates corrected by hand."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.bonds import (
    DEFAULT_ROLLOVER_PRICE,
    BondSeries,
    BondType,
    RateCorrection,
    SeriesTerms,
    bond_type_of,
    correction_of,
    series_name,
)


def _terms(series: str, rates: tuple[Decimal | None, ...], margin: Decimal | None = Decimal("0.02")) -> SeriesTerms:
    return SeriesTerms(
        series, "PL0", date(2026, 10, 1), date(2026, 10, 31), Decimal(100), Decimal("99.9"), margin, rates, (None,)
    )


@pytest.mark.parametrize(
    ("bond_type", "day", "series"),
    [
        (BondType.EDO, date(2026, 10, 12), "EDO1036"),
        (BondType.OTS, date(2026, 10, 31), "OTS0127"),
        (BondType.ROR, date(2026, 12, 1), "ROR1227"),
        (BondType.DOR, date(2026, 11, 5), "DOR1128"),
        (BondType.TOS, date(2026, 1, 2), "TOS0129"),
        (BondType.COI, date(2026, 10, 12), "COI1030"),
        (BondType.ROS, date(2026, 10, 12), "ROS1032"),
        (BondType.ROD, date(2026, 10, 12), "ROD1038"),
    ],
)
def test_the_type_and_purchase_day_give_the_series_named_by_its_maturity(
    bond_type: BondType, day: date, series: str
) -> None:
    assert series_name(bond_type, day) == series


def test_a_series_name_gives_its_bond_type() -> None:
    assert bond_type_of("EDO0836") is BondType.EDO
    assert bond_type_of("edo0836") is None  # names are upper case, as MF and the sheet write them
    assert bond_type_of("PKO BP") is None
    assert bond_type_of("ABC0836") is None


def test_a_series_has_the_mf_rates_and_one_period_per_year_of_its_term_even_unpublished() -> None:
    series = BondSeries(1, "EDO1036", _terms("EDO1036", (Decimal("0.0535"), *([None] * 9))))

    assert series.bond_type is BondType.EDO
    assert series.first_rate == Decimal("0.0535")
    assert series.margin == Decimal("0.02")
    assert series.rates == (Decimal("0.0535"), *([None] * 9))
    assert series.rollover_price == Decimal("99.9")


def test_a_series_missing_from_the_mf_file_has_its_periods_empty_and_the_default_rollover_price() -> None:
    series = BondSeries(1, "COI0130", None)

    assert series.rates == (None, None, None, None)
    assert series.margin is None
    assert series.rollover_price == DEFAULT_ROLLOVER_PRICE == Decimal("99.90")


def test_family_bonds_are_never_bought_in_a_rollover() -> None:
    assert BondSeries(1, "ROS1032", None).rollover_price is None


def test_a_correction_overrides_only_the_rates_it_sets() -> None:
    mf = _terms("EDO0525", (Decimal("0.025"), Decimal("0.015"), *([None] * 8)))
    correction = RateCorrection(margin=Decimal("0.0175"), rates=(None, Decimal("0.016"), Decimal("0.035")))
    series = BondSeries(1, "EDO0525", mf, correction)

    assert series.margin == Decimal("0.0175")
    assert series.rates[:4] == (Decimal("0.025"), Decimal("0.016"), Decimal("0.035"), None)
    assert [series.is_corrected(period) for period in range(4)] == [False, True, True, False]
    assert series.margin_is_corrected


def test_a_later_mf_rate_shows_through_where_nothing_was_corrected() -> None:
    correction = RateCorrection(rates=(Decimal("0.06"),))
    later = _terms("EDO1036", (Decimal("0.0535"), Decimal("0.045"), *([None] * 8)))

    assert BondSeries(1, "EDO1036", later, correction).rates[:2] == (Decimal("0.06"), Decimal("0.045"))


def test_entered_rates_equal_to_the_mf_ones_are_no_correction() -> None:
    mf = _terms("EDO1036", (Decimal("0.0535"), *([None] * 9)))

    correction = correction_of(mf, Decimal("0.02"), (Decimal("0.0535"), Decimal("0.05"), *([None] * 8)))

    assert correction == RateCorrection(margin=None, rates=(None, Decimal("0.05")))
    assert correction_of(mf, Decimal("0.02"), (Decimal("0.0535"), *([None] * 9))) == RateCorrection()


def test_without_mf_terms_every_entered_rate_is_a_correction() -> None:
    assert correction_of(None, Decimal("0.015"), (Decimal("0.0475"), None, None, None)) == RateCorrection(
        Decimal("0.015"), (Decimal("0.0475"),)
    )
