"""EDO, ROS, ROD, TOS and OTS valuation by the MF issue letters (L-3, L-7, spec 3.4.1): one bond's value, compounded
yearly and accrued linearly within the year (an OTS over its days out of 365), rounded to the grosz once; the rates MF
has not published estimated from GUS CPI, else forecast from the last reading."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from financial_app.domain.bond_valuation import BondData, BondValue, Cpi, PeriodRate, RateLabel, bond_value, rate_text
from financial_app.domain.bonds import BondSeries, BondType, CpiReading, RateCorrection, SeriesTerms, maturity
from financial_app.domain.lots import Lot
from financial_app.sources.bond_data import parse_mf_file

MF_FILE = Path(__file__).parent / "fixtures" / "mf" / "dane_obligacji_detalicznych.xls"
FIRST_RATE = Decimal("0.0535")


def _series(
    name: str = "EDO0536", rates: tuple[Decimal | None, ...] = (FIRST_RATE,) + (None,) * 9, instrument_id: int = 1
) -> BondSeries:
    terms = SeriesTerms(
        name, "PL0", date(2026, 5, 1), date(2026, 5, 31), Decimal(100), Decimal("99.9"), Decimal("0.02"), rates, (None,)
    )
    return BondSeries(instrument_id, name, terms)


def _cpi(year: int, month: int, index: str) -> CpiReading:
    return CpiReading(year, month, Decimal(index), None)


def test_in_the_first_year_one_bond_accrues_linearly_and_is_rounded_to_the_grosz() -> None:
    # 139 of 365 days at 5.35%: 2.0374 PLN of interest, as the sheet's "cena" of the same purchase
    value = bond_value(_series(), date(2026, 5, 22), date(2026, 10, 8), Cpi(()))

    assert value == BondValue(Decimal("102.04"), 1, PeriodRate(FIRST_RATE), None)


def test_a_bond_is_worth_its_nominal_on_its_purchase_day() -> None:
    value = bond_value(_series(), date(2026, 5, 22), date(2026, 5, 22), Cpi(()))

    assert value is not None and value.value == Decimal("100.00")


def test_a_matured_series_is_worth_what_mf_paid_out_also_after_maturity() -> None:
    edo = next(terms for terms in parse_mf_file(MF_FILE.read_bytes()) if terms.series == "EDO0525")
    series = BondSeries(1, "EDO0525", edo)

    at_maturity = bond_value(series, date(2015, 5, 15), date(2025, 5, 15), Cpi(()))
    later = bond_value(series, date(2015, 5, 15), date(2025, 9, 1), Cpi(()))

    assert edo.interest == (Decimal("73.77"),)
    assert at_maturity is not None and at_maturity.value == Decimal("173.77")
    assert later == at_maturity


def test_every_matured_edo_series_in_the_mf_file_matches_its_interest() -> None:
    """MF compounds the yearly rates without rounding between years, then rounds the bond once."""
    for terms in parse_mf_file(MF_FILE.read_bytes()):
        if terms.bond_type != "EDO" or None in terms.rates or terms.interest[0] is None:
            continue
        start = terms.sale_start
        value = bond_value(
            BondSeries(1, terms.series, terms), start, date(start.year + 10, start.month, start.day), Cpi(())
        )
        assert value is not None and value.value - 100 == terms.interest[0], terms.series


def test_a_later_year_compounds_the_years_before_and_accrues_over_its_own_days() -> None:
    # Year 2 runs 22.05.2027-22.05.2028, 366 days with 29 February; 184 of them gone
    series = _series(rates=(FIRST_RATE, Decimal("0.05")) + (None,) * 8)

    value = bond_value(series, date(2026, 5, 22), date(2027, 11, 22), Cpi(()))

    # 100 x 1.0535 x (1 + 0.05 x 184 / 366)
    assert value == BondValue(Decimal("108.00"), 2, PeriodRate(Decimal("0.05")), None)


def test_an_unpublished_rate_is_estimated_from_the_cpi_two_months_before_the_anniversary() -> None:
    cpi = (_cpi(2027, 2, "104.0"), _cpi(2027, 3, "103.0"))

    value = bond_value(_series(), date(2026, 5, 22), date(2027, 11, 22), Cpi(cpi))

    estimated = PeriodRate(Decimal("0.05"), RateLabel.ESTIMATED_CPI)
    assert value == BondValue(Decimal("108.00"), 2, estimated, RateLabel.ESTIMATED_CPI)


def test_without_the_cpi_of_that_month_the_last_reading_forecasts_the_rate() -> None:
    cpi = (_cpi(2027, 1, "104.0"), _cpi(2027, 2, "103.4"))

    value = bond_value(_series(), date(2026, 5, 22), date(2027, 5, 22), Cpi(cpi))

    assert value == BondValue(
        Decimal("105.35"), 2, PeriodRate(Decimal("0.054"), RateLabel.FORECAST_CPI), RateLabel.FORECAST_CPI
    )


def test_deflation_leaves_the_margin_as_mf_paid_in_2015_and_2016() -> None:
    value = bond_value(_series(), date(2026, 5, 22), date(2027, 11, 22), Cpi((_cpi(2027, 3, "97.0"),)))

    assert value is not None and value.rate == PeriodRate(Decimal("0.02"), RateLabel.ESTIMATED_CPI)
    # 100 x 1.0535 x (1 + 0.02 x 184 / 366)
    assert value.value == Decimal("106.41")


def test_a_lot_dated_after_the_day_is_worth_its_nominal() -> None:
    value = bond_value(_series(), date(2026, 5, 22), date(2026, 5, 20), Cpi(()))

    assert value == BondValue(Decimal("100.00"), 1, PeriodRate(FIRST_RATE), None)


def test_a_value_resting_on_an_estimated_year_keeps_its_label_in_a_published_one() -> None:
    series = _series(rates=(FIRST_RATE, None, Decimal("0.05")) + (None,) * 7)

    value = bond_value(series, date(2026, 5, 22), date(2028, 6, 1), Cpi((_cpi(2027, 3, "103.0"),)))

    assert value is not None and value.rate == PeriodRate(Decimal("0.05")) and value.period == 3
    assert value.label is RateLabel.ESTIMATED_CPI


def test_a_corrected_rate_counts_as_published() -> None:
    series = BondSeries(1, "EDO0536", _series().mf, RateCorrection(rates=(None, Decimal("0.05"))))

    value = bond_value(series, date(2026, 5, 22), date(2027, 11, 22), Cpi(()))

    assert value is not None and value.value == Decimal("108.00") and value.label is None


def test_a_bond_bought_on_29_february_has_its_anniversary_on_28_february() -> None:
    series = _series("EDO0238", (FIRST_RATE, Decimal("0.05")) + (None,) * 8)

    value = bond_value(series, date(2028, 2, 29), date(2029, 2, 28), Cpi(()))

    assert value is not None and (value.value, value.period) == (Decimal("105.35"), 2)


def test_without_a_first_rate_or_cpi_for_a_later_year_there_is_no_value() -> None:
    assert bond_value(BondSeries(1, "EDO0536", None), date(2026, 5, 22), date(2026, 6, 1), Cpi(())) is None
    assert bond_value(_series(), date(2026, 5, 22), date(2027, 6, 1), Cpi(())) is None


def test_the_coupon_types_are_not_valued_yet() -> None:
    assert bond_value(_series("COI0530"), date(2026, 5, 22), date(2026, 6, 1), Cpi(())) is None


@pytest.mark.parametrize("bond_type", ["TOS", "ROS"])
def test_every_matured_tos_and_ros_series_in_the_mf_file_matches_its_interest(bond_type: str) -> None:
    """TOS compounds its one fixed rate yearly, ROS its yearly rates as EDO; both rounded once."""
    matured = 0
    for terms in parse_mf_file(MF_FILE.read_bytes()):
        if terms.bond_type != bond_type or None in terms.rates or terms.interest[0] is None:
            continue
        start = terms.sale_start
        end = maturity(terms.bond_type, start)
        value = bond_value(BondSeries(1, terms.series, terms), start, end, Cpi(()))
        assert value is not None and value.value - 100 == terms.interest[0], terms.series
        matured += 1
    assert matured > 0


def test_every_ots_series_in_the_mf_file_pays_its_rate_over_the_days_of_its_three_months() -> None:
    """OTS pays 100 x rate x days / 365 at maturity, in a leap year too; MF lists a purchase on the first day."""
    for terms in parse_mf_file(MF_FILE.read_bytes()):
        if terms.bond_type != "OTS" or terms.interest[0] is None:
            continue
        start = terms.sale_start
        value = bond_value(BondSeries(1, terms.series, terms), start, maturity(BondType.OTS, start), Cpi(()))
        assert value is not None and value.value - 100 == terms.interest[0], terms.series


def test_an_ots_accrues_linearly_over_365_days_a_year() -> None:
    series = _series("OTS0127", (Decimal("0.02"),))

    # 30 days at 2%: 0.1644 PLN
    value = bond_value(series, date(2026, 10, 5), date(2026, 11, 4), Cpi(()))

    assert value == BondValue(Decimal("100.16"), None, PeriodRate(Decimal("0.02")), None)


def test_a_tos_compounds_its_fixed_rate_in_every_year_without_cpi() -> None:
    series = _series("TOS1028", (Decimal("0.0515"),))

    # Year 2 runs 05.10.2026-05.10.2027, 365 days; 184 of them gone: 100 x 1.0515 x (1 + 0.0515 x 184 / 365)
    value = bond_value(series, date(2025, 10, 5), date(2027, 4, 7), Cpi(()))

    assert value == BondValue(Decimal("107.88"), 2, PeriodRate(Decimal("0.0515")), None)


@pytest.mark.parametrize("name", ["ROS0532", "ROD0538"])
def test_a_family_bond_estimates_its_later_years_from_cpi_as_edo(name: str) -> None:
    cpi = (_cpi(2027, 3, "103.0"),)

    value = bond_value(_series(name, (FIRST_RATE,) + (None,) * 11), date(2026, 5, 22), date(2027, 11, 22), Cpi(cpi))

    estimated = PeriodRate(Decimal("0.05"), RateLabel.ESTIMATED_CPI)
    assert value == BondValue(Decimal("108.00"), 2, estimated, RateLabel.ESTIMATED_CPI)


def test_the_rate_text_names_the_year_unless_the_bond_runs_months() -> None:
    edo = bond_value(_series(), date(2026, 5, 22), date(2026, 10, 8), Cpi(()))
    ots = bond_value(_series("OTS0127", (Decimal("0.02"),)), date(2026, 10, 5), date(2026, 11, 4), Cpi(()))

    assert edo is not None and rate_text(edo) == "5,35 % · rok 1"
    assert ots is not None and rate_text(ots) == "2,00 %"


def test_a_lot_bought_in_a_rollover_is_valued_from_the_nominal_like_any_other() -> None:
    data = BondData({1: _series()}, ())
    price = data.price(1, date(2026, 10, 8))

    assert price is not None
    assert price.of(Lot(date(2026, 5, 22), Decimal(50), Decimal(4995), Decimal(4995))) == Decimal("102.04")


def test_a_lot_without_a_value_counts_at_its_cost() -> None:
    price = BondData({1: _series()}, ()).price(1, date(2027, 6, 1))

    assert price is not None
    assert price.of(Lot(date(2026, 5, 22), Decimal(50), Decimal(5000), Decimal(5000))) == Decimal(100)


@pytest.mark.parametrize("name", ["COI0530", "EDO0536"])
def test_only_a_valued_series_with_a_first_rate_has_a_price(name: str) -> None:
    data = BondData({1: _series(name), 2: BondSeries(2, "EDO0636", None)}, ())

    assert (data.price(1, date(2026, 6, 1)) is not None) is (name == "EDO0536")
    assert data.price(2, date(2026, 6, 1)) is None
    assert data.price(3, date(2026, 6, 1)) is None
