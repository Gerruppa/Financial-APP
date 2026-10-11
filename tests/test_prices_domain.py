"""Which Price Sources an Instrument is priced from, in which order (issue #30, spec 4.1), and when the prices are
refreshed at start-up (issue #38)."""

from datetime import date, datetime

from financial_app.domain.prices import BOSSA, SESSION_CLOSE, YAHOO, last_weekday_close, refresh_due, sources_to_try


def test_an_instrument_is_tried_in_its_asset_classs_order() -> None:
    order = sources_to_try("Akcje polskie", {YAHOO: "PZU.WA", BOSSA: "PZU"})

    assert order == [(BOSSA, "PZU"), (YAHOO, "PZU.WA")]


def test_a_source_without_the_instruments_symbol_is_skipped() -> None:
    # Akcje zagraniczne try Yahoo, then Bossa; an LSE ETF has no Bossa symbol
    assert sources_to_try("Akcje zagraniczne", {YAHOO: "ISAC.L"}) == [(YAHOO, "ISAC.L")]


def test_an_asset_class_the_user_added_is_tried_like_inne() -> None:
    symbols = {YAHOO: "X", BOSSA: "Y"}

    assert sources_to_try("Nieruchomości", symbols) == sources_to_try("Inne", symbols) == [(YAHOO, "X"), (BOSSA, "Y")]


def test_cash_and_polish_treasury_bonds_are_never_fetched() -> None:
    for asset_class in ("Gotówka", "Waluty", "Obligacje skarbowe polskie"):
        assert sources_to_try(asset_class, {YAHOO: "X", BOSSA: "Y"}) == []


# 2026-10-09 is a Friday
FRIDAY_EVENING = datetime(2026, 10, 9, 19, 0)


def test_a_start_after_the_weekday_close_refreshes_when_the_last_success_was_before_it() -> None:
    assert refresh_due(datetime(2026, 10, 9, 12, 0), FRIDAY_EVENING)


def test_a_second_start_the_same_evening_does_not_refresh_again() -> None:
    assert not refresh_due(datetime(2026, 10, 9, 18, 0), FRIDAY_EVENING)


def test_a_weekend_start_after_a_friday_evening_refresh_does_not_refresh() -> None:
    assert not refresh_due(datetime(2026, 10, 9, 18, 0), datetime(2026, 10, 11, 10, 0))


def test_a_weekend_start_refreshes_when_the_last_success_was_before_fridays_close() -> None:
    assert refresh_due(datetime(2026, 10, 9, 12, 0), datetime(2026, 10, 10, 10, 0))


def test_a_start_before_the_close_counts_back_to_the_previous_weekdays_close() -> None:
    monday_morning = datetime(2026, 10, 12, 9, 0)

    assert not refresh_due(datetime(2026, 10, 9, 18, 0), monday_morning)
    assert refresh_due(datetime(2026, 10, 9, 17, 0), monday_morning)


def test_the_close_itself_is_after_the_session() -> None:
    assert last_weekday_close(datetime.combine(date(2026, 10, 9), SESSION_CLOSE)) == datetime.combine(
        date(2026, 10, 9), SESSION_CLOSE
    )


def test_the_first_start_refreshes() -> None:
    assert refresh_due(None, FRIDAY_EVENING)
