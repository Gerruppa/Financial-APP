"""The Instrument Card's figures (issue #175), without the network."""

from datetime import date
from decimal import Decimal

from financial_app.domain.instrument_card import CardPeriod, chart_window, price_summary, returns
from financial_app.domain.prices import YAHOO, Quote


def _quotes(*prices: tuple[str, str]) -> list[Quote]:
    return [Quote(Decimal(price), "USD", date.fromisoformat(day), YAHOO) for day, price in prices]


# Worked by hand: the last close is 147 on 20.10.2026, the year before closed at 125, the day before at 140
HISTORY = _quotes(
    ("2024-12-31", "100"),
    ("2025-06-30", "110"),
    ("2025-10-20", "120"),
    ("2025-12-31", "125"),
    ("2026-09-18", "130"),
    ("2026-10-19", "140"),
    ("2026-10-20", "147"),
)


def test_the_price_panel_shows_the_last_close_its_change_from_the_day_before_and_from_the_year_end() -> None:
    summary = price_summary(HISTORY)

    assert summary is not None
    assert (summary.price, summary.currency, summary.day) == (Decimal(147), "USD", date(2026, 10, 20))
    assert summary.day_change_percent == Decimal(5)
    assert summary.ytd_percent == Decimal("17.6")


def test_the_twelve_months_low_and_high_count_the_closes_since_the_same_day_a_year_before() -> None:
    summary = price_summary(HISTORY)

    assert summary is not None
    assert (summary.low_12m, summary.high_12m) == (Decimal(120), Decimal(147))


def test_one_close_has_no_change_and_no_history_has_no_price_panel() -> None:
    summary = price_summary(_quotes(("2026-10-20", "50")))

    assert summary is not None
    assert (summary.day_change_percent, summary.ytd_percent) == (None, None)
    assert (summary.low_12m, summary.high_12m) == (Decimal(50), Decimal(50))
    assert price_summary([]) is None


def test_each_of_the_last_five_calendar_years_returns_from_the_close_before_it_none_without_one() -> None:
    table = returns(HISTORY)

    assert table.years == {
        2026: Decimal("17.6"),
        2025: Decimal(25),
        2024: None,
        2023: None,
        2022: None,
    }


def test_a_period_returns_from_the_last_close_on_or_before_its_start_none_when_history_is_shorter() -> None:
    table = returns(HISTORY)

    assert round(table.periods[CardPeriod.ONE_MONTH], 4) == Decimal("13.0769")  # type: ignore[arg-type]
    assert table.periods[CardPeriod.THREE_MONTHS] == Decimal("17.6")
    assert table.periods[CardPeriod.SIX_MONTHS] == Decimal("17.6")
    assert table.periods[CardPeriod.ONE_YEAR] == Decimal("22.5")
    assert table.periods[CardPeriod.THREE_YEARS] is None


def test_the_chart_shows_the_closes_since_the_period_start_ytd_from_the_last_close_of_the_year_before() -> None:
    def days(period: CardPeriod) -> list[str]:
        return [quote.day.isoformat() for quote in chart_window(HISTORY, period)]

    assert days(CardPeriod.ONE_MONTH) == ["2026-09-18", "2026-10-19", "2026-10-20"]
    assert days(CardPeriod.YEAR_TO_DATE) == ["2025-12-31", "2026-09-18", "2026-10-19", "2026-10-20"]
    assert days(CardPeriod.ONE_YEAR) == ["2025-10-20", "2025-12-31", "2026-09-18", "2026-10-19", "2026-10-20"]
    assert days(CardPeriod.MAX) == [quote.day.isoformat() for quote in HISTORY]
    assert days(CardPeriod.FIVE_YEARS) == days(CardPeriod.MAX)
