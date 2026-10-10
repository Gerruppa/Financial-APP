"""Quotes from the Bossa JSON API, one request per category (issue #31, spec 4.1), on saved responses."""

from datetime import date
from decimal import Decimal
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from financial_app.domain.prices import BOSSA, PriceSourceError, Quote
from financial_app.sources.bossa import BossaSource

FIXTURES = Path(__file__).parent / "fixtures" / "bossa"
FRIDAY = date(2026, 10, 2)


class SavedBossa:
    """Answers each category URL from its saved response and counts the requests."""

    def __init__(self, failing: dict[str, OSError] | None = None) -> None:
        self.failing = failing or {}
        self.asked: list[str] = []

    def __call__(self, url: str) -> str:
        category = url.rsplit("/", 1)[1]
        self.asked.append(category)
        if category in self.failing:
            raise self.failing[category]
        return (FIXTURES / f"{category}.json").read_text(encoding="utf-8")


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_gpw_share_is_quoted_by_its_short_symbol_with_its_session_day() -> None:
    assert BossaSource(SavedBossa()).quote("PZU", "PLN") == Quote(Decimal("69.8200"), "PLN", FRIDAY, BOSSA)


def test_the_full_symbol_and_any_case_or_a_wse_prefix_also_find_it() -> None:
    source = BossaSource(SavedBossa())

    assert source.quote("cdprojekt", "PLN").price == Decimal("253.5000")
    assert source.quote("WSE:CDR", "PLN").price == Decimal("253.5000")


def test_without_a_trade_the_reference_price_is_the_quote() -> None:
    assert BossaSource(SavedBossa()).quote("ATP", "PLN").price == Decimal("23.0000")


@pytest.mark.parametrize(
    ("symbol", "price"),
    [("ONE", "0.0992"), ("ETFBDIVPL", "297.7500"), ("ACH0427", "101.00"), ("ABE0227", "100.00")],
)
def test_newconnect_etfs_and_catalyst_bonds_are_quoted_too(symbol: str, price: str) -> None:
    assert BossaSource(SavedBossa()).quote(symbol, "PLN").price == Decimal(price)


def test_one_request_per_category_whatever_the_number_of_instruments() -> None:
    fetch = SavedBossa()
    source = BossaSource(fetch)

    for symbol in ("PZU", "CDR", "11B", "ONE", "BGD", "ACH0427", "ETFBDIVPL"):
        source.quote(symbol, "PLN")

    assert sorted(fetch.asked) == ["_cat_bonds", "_cat_etf", "_cat_nConnect", "_cat_shares"]


def test_only_the_categories_needed_are_requested() -> None:
    fetch = SavedBossa()

    BossaSource(fetch).quote("PZU", "PLN")

    assert fetch.asked == ["_cat_shares"]


def test_a_later_refresh_requests_the_categories_again() -> None:
    fetch, clock = SavedBossa(), Clock()
    source = BossaSource(fetch, clock)
    source.quote("PZU", "PLN")

    clock.now += 10 * 60
    source.quote("PZU", "PLN")

    assert fetch.asked == ["_cat_shares", "_cat_shares"]


def test_an_unknown_symbol_is_an_error() -> None:
    with pytest.raises(PriceSourceError, match="Bossa nie zna symbolu „XYZ”"):
        BossaSource(SavedBossa()).quote("XYZ", "PLN")


def test_an_instrument_quoted_in_another_currency_is_an_error() -> None:
    with pytest.raises(PriceSourceError, match="PLN.*USD"):
        BossaSource(SavedBossa()).quote("PZU", "USD")


def test_without_a_connection_the_error_says_so() -> None:
    fetch = SavedBossa({"_cat_shares": URLError("offline")})

    with pytest.raises(PriceSourceError, match="Nie udało się połączyć z Bossa"):
        BossaSource(fetch).quote("PZU", "PLN")


def test_a_category_that_failed_is_requested_again_on_the_next_quote() -> None:
    error = HTTPError("url", 503, "Service Unavailable", Message(), None)
    fetch = SavedBossa({"_cat_shares": error})
    source = BossaSource(fetch)
    with pytest.raises(PriceSourceError, match="HTTP 503"):
        source.quote("PZU", "PLN")

    fetch.failing.clear()

    assert source.quote("PZU", "PLN").price == Decimal("69.8200")


def test_a_symbol_found_in_a_later_category_is_quoted_even_when_an_earlier_one_failed() -> None:
    fetch = SavedBossa({"_cat_shares": URLError("offline")})

    assert BossaSource(fetch).quote("ETFBDIVPL", "PLN").price == Decimal("297.7500")


def test_a_malformed_response_is_an_error() -> None:
    with pytest.raises(PriceSourceError, match="Nieprawidłowa odpowiedź Bossa"):
        BossaSource(lambda url: "<html>").quote("PZU", "PLN")
