"""The interest periods of a Bond Series as the bond help window lists them (issue #272): each period's dates, its rate
as the valuation takes it and where that rate comes from."""

from datetime import date
from decimal import Decimal

from financial_app.domain.bond_guide import GuidePeriod, guide_periods
from financial_app.domain.bond_valuation import Cpi, ReferenceRates
from financial_app.domain.bonds import BondSeries, CpiReading, RateCorrection, ReferenceRate, SeriesTerms


def _terms(name: str, rates: tuple[Decimal | None, ...], margin: str | None = "0.02") -> SeriesTerms:
    return SeriesTerms(
        name,
        "PL0000000000",
        date(2026, 10, 1),
        date(2026, 10, 31),
        Decimal(100),
        Decimal("99.9"),
        None if margin is None else Decimal(margin),
        rates,
        (),
    )


def test_an_edo_has_ten_yearly_periods_the_first_from_mf_the_rest_estimated_from_cpi() -> None:
    series = BondSeries(1, "EDO1036", _terms("EDO1036", (Decimal("0.0535"), None)))
    cpi = Cpi([CpiReading(2027, 8, Decimal("103.4"), None)])

    periods = guide_periods(series, date(2026, 10, 12), cpi, ReferenceRates(()))

    assert len(periods) == 10
    assert periods[0] == GuidePeriod(1, date(2026, 10, 12), date(2027, 10, 12), Decimal("0.0535"), "z pliku MF")
    # Year 2 takes CPI of August 2027, two months before its anniversary, plus the 2% margin
    assert periods[1] == GuidePeriod(2, date(2027, 10, 12), date(2028, 10, 12), Decimal("0.054"), "szacowana (CPI)")
    assert periods[2].source == "prognoza (ostatnie CPI)"
    assert periods[9].end == date(2036, 10, 12)


def test_a_corrected_rate_says_so() -> None:
    series = BondSeries(1, "EDO1036", _terms("EDO1036", (Decimal("0.0535"),)), RateCorrection(rates=(Decimal("0.06"),)))

    first = guide_periods(series, date(2026, 10, 12), Cpi([]), ReferenceRates(()))[0]

    assert (first.rate, first.source) == (Decimal("0.06"), "poprawione ręcznie")


def test_a_period_without_any_data_has_no_rate() -> None:
    series = BondSeries(None, "EDO1036", None)

    first = guide_periods(series, date(2026, 10, 12), Cpi([]), ReferenceRates(()))[0]

    assert (first.rate, first.source) == (None, "brak danych")


def test_a_tos_keeps_its_fixed_rate_every_year() -> None:
    series = BondSeries(1, "TOS1029", _terms("TOS1029", (Decimal("0.05"),), margin=None))

    periods = guide_periods(series, date(2026, 10, 12), Cpi([]), ReferenceRates(()))

    assert [(p.rate, p.source) for p in periods] == [(Decimal("0.05"), "z pliku MF")] * 3


def test_an_ots_is_one_period_of_three_months() -> None:
    series = BondSeries(1, "OTS0127", _terms("OTS0127", (Decimal("0.03"),), margin=None))

    periods = guide_periods(series, date(2026, 10, 12), Cpi([]), ReferenceRates(()))

    assert periods == (GuidePeriod(1, date(2026, 10, 12), date(2027, 1, 12), Decimal("0.03"), "z pliku MF"),)


def test_a_ror_has_twelve_monthly_periods_following_the_nbp_reference_rate() -> None:
    series = BondSeries(1, "ROR1027", _terms("ROR1027", (Decimal("0.0475"),), margin="0"))
    reference = ReferenceRates([ReferenceRate(date(2026, 1, 1), Decimal("0.0475"))], date(2026, 12, 31))

    periods = guide_periods(series, date(2026, 10, 12), Cpi([]), reference)

    assert len(periods) == 12
    assert periods[1] == GuidePeriod(2, date(2026, 11, 12), date(2026, 12, 12), Decimal("0.0475"), "szacowana (NBP)")
