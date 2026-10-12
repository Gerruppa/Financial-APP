"""The period selector shared by charts and results (issue #71, spec section 5 and 6.1): presets and a custom range,
the "from" day being where returns start, remembered as text."""

from datetime import date

import pytest

from financial_app.domain.periods import Period, PeriodError, PeriodPreset, parse_period, period_dates, period_setting

TODAY = date(2026, 3, 31)
INCEPTION = date(2020, 6, 15)


@pytest.mark.parametrize(
    ("preset", "first"),
    [
        (PeriodPreset.ONE_MONTH, date(2026, 2, 28)),
        (PeriodPreset.THREE_MONTHS, date(2025, 12, 31)),
        (PeriodPreset.YEAR_TO_DATE, date(2025, 12, 31)),
        (PeriodPreset.ONE_YEAR, date(2025, 3, 31)),
        (PeriodPreset.THREE_YEARS, date(2023, 3, 31)),
        (PeriodPreset.FIVE_YEARS, date(2021, 3, 31)),
        (PeriodPreset.SINCE_INCEPTION, INCEPTION),
    ],
)
def test_a_preset_runs_from_its_from_day_to_today(preset: PeriodPreset, first: date) -> None:
    assert period_dates(Period(preset), TODAY, INCEPTION) == (first, TODAY)


def test_a_period_before_the_first_transaction_is_clipped_to_it() -> None:
    assert period_dates(Period(PeriodPreset.ONE_YEAR), date(2020, 12, 1), INCEPTION) == (INCEPTION, date(2020, 12, 1))
    custom = Period(PeriodPreset.CUSTOM, date(2019, 1, 1), date(2021, 1, 1))
    assert period_dates(custom, TODAY, INCEPTION) == (INCEPTION, date(2021, 1, 1))


def test_without_transactions_a_period_is_not_clipped() -> None:
    assert period_dates(Period(PeriodPreset.ONE_MONTH), TODAY, None) == (date(2026, 2, 28), TODAY)
    assert period_dates(Period(PeriodPreset.SINCE_INCEPTION), TODAY, None) == (TODAY, TODAY)


def test_a_custom_range_is_kept_as_entered_up_to_today() -> None:
    custom = Period(PeriodPreset.CUSTOM, date(2024, 1, 1), date(2027, 1, 1))

    assert period_dates(custom, TODAY, INCEPTION) == (date(2024, 1, 1), TODAY)


def test_a_custom_range_needs_both_days_in_order() -> None:
    with pytest.raises(PeriodError, match="Data początkowa"):
        Period(PeriodPreset.CUSTOM, date(2024, 2, 1), date(2024, 1, 1))
    with pytest.raises(PeriodError, match="Podaj"):
        Period(PeriodPreset.CUSTOM, date(2024, 2, 1))


def test_the_period_is_stored_as_text_and_an_unreadable_one_is_since_inception() -> None:
    custom = Period(PeriodPreset.CUSTOM, date(2024, 1, 1), date(2024, 6, 30))

    assert period_setting(Period(PeriodPreset.YEAR_TO_DATE)) == "ytd"
    assert parse_period("ytd") == Period(PeriodPreset.YEAR_TO_DATE)
    assert period_setting(custom) == "custom:2024-01-01:2024-06-30"
    assert parse_period("custom:2024-01-01:2024-06-30") == custom
    assert parse_period(None) == Period(PeriodPreset.SINCE_INCEPTION)
    assert parse_period("custom:2024-06-30:2024-01-01") == Period(PeriodPreset.SINCE_INCEPTION)
    assert parse_period("decade") == Period(PeriodPreset.SINCE_INCEPTION)


def test_presets_have_polish_labels() -> None:
    assert [preset.label for preset in PeriodPreset] == ["1M", "3M", "YTD", "1R", "3L", "5L", "Od początku", "Własny"]
