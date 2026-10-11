"""Instrument search through Yahoo (issue #25, spec 4.1), on saved responses without the network."""

from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, unquote, urlparse

import pytest

from financial_app.domain.instrument_search import InstrumentSearchError, SearchResult
from financial_app.domain.prices import BOSSA, YAHOO
from financial_app.sources.yahoo import YahooSearch

FIXTURES = Path(__file__).parent / "fixtures" / "yahoo"


def _saved(url: str) -> str | None:
    """The saved search or chart response for ``url``; a search without one finds nothing, a chart is HTTP 404."""
    parsed = urlparse(url)
    if "/search" in parsed.path:
        query = parse_qs(parsed.query)["q"][0]
        path = FIXTURES / "search" / f"{query.replace(' ', '_')}.json"
        return path.read_text(encoding="utf-8") if path.is_file() else '{"count": 0, "quotes": []}'
    path = FIXTURES / f"{unquote(parsed.path.split('/chart/')[1])}.json"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def test_an_isin_finds_every_listing_of_the_fund_with_its_currency() -> None:
    results = YahooSearch(_saved).search("ie00b6r52259")

    name = "iShares MSCI All Country World UCITS ETF USD Acc"
    assert {(r.symbol, r.market, r.currency) for r in results} == {
        ("ISAC.L", "London", "USD"),
        ("IUSQ.DE", "XETRA", "EUR"),
        ("SSAC.SW", "Swiss", "CHF"),
        ("SSAC.L", "London", "GBP"),
        ("SSAC.AS", "Amsterdam", "EUR"),
        ("ISAC.MI", "Milan", "EUR"),
    }
    assert all(r.name == name and r.isin == "IE00B6R52259" for r in results)
    # The listing Yahoo matched to the ISIN comes first
    assert results[0].symbol == "ISAC.L"


def test_a_name_finds_listings_without_an_isin_and_warsaw_is_gpw() -> None:
    results = YahooSearch(_saved).search("cd projekt")

    assert results[0] == SearchResult(
        name="CD Projekt Red S.A.",
        symbol="CDR.WA",
        market="GPW",
        currency="PLN",
        source_symbols={YAHOO: "CDR.WA", BOSSA: "CDR"},
    )
    assert len(results) == 7


def test_a_listing_whose_chart_fails_has_no_currency() -> None:
    def no_charts(url: str) -> str | None:
        return _saved(url) if "/search" in url else None

    results = YahooSearch(no_charts).search("cd projekt")

    assert {r.currency for r in results} == {""}


def test_nothing_found_is_an_empty_list() -> None:
    assert YahooSearch(_saved).search("PLFIO0000014") == []
    assert YahooSearch(_saved).search("   ") == []


def test_no_network_is_a_polish_error() -> None:
    def offline(url: str) -> str | None:
        raise URLError("offline")

    with pytest.raises(InstrumentSearchError, match="połączyć"):
        YahooSearch(offline).search("ISAC")


def test_an_unexpected_response_is_a_polish_error() -> None:
    with pytest.raises(InstrumentSearchError, match="Nieprawidłowa"):
        YahooSearch(lambda url: "<html>").search("ISAC")


def test_only_a_warsaw_listing_gives_a_bossa_symbol() -> None:
    results = YahooSearch(_saved).search("IE00B6R52259")

    assert results[0].source_symbols == {YAHOO: "ISAC.L"}
