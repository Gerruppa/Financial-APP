"""The header search's results and the Instrument Card's figures (issue #175), without the network."""

from datetime import date
from decimal import Decimal

from financial_app.domain.instrument_card import (
    chart_window,
    group_results,
    matching_instruments,
    owned_instrument,
    price_summary,
    returns,
)
from financial_app.domain.instrument_search import SearchResult
from financial_app.domain.instruments import Instrument
from financial_app.domain.prices import ANALIZY, BOSSA, YAHOO, Quote


def _instrument(id: int, name: str, symbols: dict[str, str], isin: str = "", currency: str = "PLN") -> Instrument:
    return Instrument(
        name, 1, currency, source_symbols=symbols, isin=isin, id=id, asset_class_name="Akcje", fallback_order=()
    )


OWN_CDR = _instrument(1, "CD Projekt", {YAHOO: "CDR.WA", BOSSA: "CDR"}, isin="PLOPTTC00011")
OWN_VUAA = _instrument(2, "Vanguard S&P 500 Acc", {YAHOO: "VUAA.L"}, isin="IE00BFMXXD54", currency="USD")
OWN_ZLOTO = _instrument(3, "Złoto fizyczne", {})
OWN = [OWN_CDR, OWN_VUAA, OWN_ZLOTO]

VUAA = SearchResult(
    name="Vanguard S&P 500 UCITS ETF USD Acc",
    symbol="VUAA.L",
    market="LSE",
    currency="USD",
    source_symbols={YAHOO: "VUAA.L"},
    isin="IE00BFMXXD54",
    fund=True,
    source="Yahoo",
)
VUAG = SearchResult(
    name="Vanguard S&P 500 UCITS ETF USD Acc",
    symbol="VUAG.L",
    market="LSE",
    currency="GBP",
    source_symbols={YAHOO: "VUAG.L"},
    isin="IE00BFMXXD54",
    fund=True,
    source="Yahoo",
)
CDR = SearchResult(
    name="CD Projekt Red S.A.",
    symbol="CDR.WA",
    market="GPW",
    currency="PLN",
    source_symbols={YAHOO: "CDR.WA"},
    asset_class="Akcje polskie",
    source="Yahoo",
)
CDR_DE = SearchResult(
    name="CD Projekt Red S.A.",
    symbol="CDR.DE",
    market="XETRA",
    currency="EUR",
    source_symbols={YAHOO: "CDR.DE"},
    asset_class="Akcje zagraniczne",
    source="Yahoo",
)
QUERCUS = SearchResult(
    name="Quercus Agresywny",
    symbol="QRS32",
    market="",
    currency="PLN",
    source_symbols={ANALIZY: "QRS32"},
    fund=True,
    source="analizy.pl",
)


def test_listings_of_one_isin_or_one_name_are_one_found_instrument_in_the_order_found() -> None:
    found = group_results([VUAA, CDR, QUERCUS, VUAG, CDR_DE])

    assert [(f.name, f.isin, [listing.symbol for listing in f.listings]) for f in found] == [
        ("Vanguard S&P 500 UCITS ETF USD Acc", "IE00BFMXXD54", ["VUAA.L", "VUAG.L"]),
        ("CD Projekt Red S.A.", "", ["CDR.WA", "CDR.DE"]),
        ("Quercus Agresywny", "", ["QRS32"]),
    ]


def test_a_found_instrument_shows_each_asset_class_and_source_of_its_listings_once() -> None:
    [cdr] = group_results([CDR, CDR_DE])
    [quercus] = group_results([QUERCUS])

    assert cdr.asset_classes == ["Akcje polskie", "Akcje zagraniczne"]
    assert cdr.sources == ["Yahoo"]
    assert quercus.asset_classes == []
    assert quercus.sources == ["analizy.pl"]


def test_own_instruments_match_a_query_in_their_name_isin_or_source_symbols_ignoring_case_and_polish_letters() -> None:
    assert matching_instruments(OWN, "projekt") == [OWN_CDR]
    assert matching_instruments(OWN, "ie00bfmx") == [OWN_VUAA]
    assert matching_instruments(OWN, "vuaa") == [OWN_VUAA]
    assert matching_instruments(OWN, "cdr") == [OWN_CDR]
    assert matching_instruments(OWN, "zloto") == [OWN_ZLOTO]


def test_an_empty_query_matches_no_own_instrument_and_at_most_the_limit_are_given() -> None:
    assert matching_instruments(OWN, "  ") == []
    assert matching_instruments(OWN, "o", limit=1) == [OWN_CDR]


def test_a_listing_is_owned_when_an_instrument_has_one_of_its_source_symbols() -> None:
    assert owned_instrument(VUAA, OWN) == OWN_VUAA
    assert owned_instrument(CDR, OWN) == OWN_CDR


def test_the_same_isin_on_another_exchange_or_currency_is_not_owned() -> None:
    assert owned_instrument(VUAG, OWN) is None
    assert owned_instrument(QUERCUS, OWN) is None


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

    assert round(table.periods["1M"], 4) == Decimal("13.0769")  # type: ignore[arg-type]
    assert table.periods["3M"] == Decimal("17.6")
    assert table.periods["6M"] == Decimal("17.6")
    assert table.periods["1R"] == Decimal("22.5")
    assert table.periods["3L"] is None


def test_the_chart_shows_the_closes_since_the_period_start_ytd_from_the_last_close_of_the_year_before() -> None:
    def days(period: str) -> list[str]:
        return [quote.day.isoformat() for quote in chart_window(HISTORY, period)]

    assert days("1M") == ["2026-09-18", "2026-10-19", "2026-10-20"]
    assert days("YTD") == ["2025-12-31", "2026-09-18", "2026-10-19", "2026-10-20"]
    assert days("1R") == ["2025-10-20", "2025-12-31", "2026-09-18", "2026-10-19", "2026-10-20"]
    assert days("Max") == [quote.day.isoformat() for quote in HISTORY]
    assert days("5L") == days("Max")
