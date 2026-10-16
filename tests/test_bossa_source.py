"""Quotes from the Bossa JSON API, one request per category (issue #31, spec 4.1), on saved responses."""

import json
from datetime import date
from decimal import Decimal
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from financial_app.domain.catalyst import BondFacts
from financial_app.domain.prices import BOSSA, CurrencyMismatchError, PriceSourceError, Quote
from financial_app.sources.bossa import BossaSource
from financial_app.sources.catalyst import CATALYST_LISTING, INDEXATION_PAGE, CatalystFacts

FIXTURES = Path(__file__).parent / "fixtures" / "bossa"
FRIDAY = date(2026, 10, 2)
CATALYST_PAGES = {
    CATALYST_LISTING: Path(__file__).parent / "fixtures" / "catalyst" / "instrumenty-notowane.html",
    INDEXATION_PAGE: Path(__file__).parent / "fixtures" / "indexation" / "wspolczynniki-indeksacji.html",
}


class FixedFacts:
    """Catalyst bond facts by symbol; counts the refreshes."""

    def __init__(self, facts: dict[str, BondFacts]) -> None:
        self.facts = facts
        self.refreshes = 0

    def of(self, symbol: str, day: date) -> BondFacts:
        if symbol not in self.facts:
            raise PriceSourceError(f"gpwcatalyst.pl nie podaje wartości nominalnej obligacji „{symbol}”.")
        return self.facts[symbol]

    def new_refresh(self) -> None:
        self.refreshes += 1


ACH0427 = FixedFacts({"ACH0427": BondFacts(Decimal("1000.00"), Decimal("2.93"))})


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
    [("ONE", "0.0992"), ("ETFBDIVPL", "297.7500")],
)
def test_newconnect_and_etfs_are_quoted_too(symbol: str, price: str) -> None:
    assert BossaSource(SavedBossa()).quote(symbol, "PLN").price == Decimal(price)


def test_a_catalyst_bond_is_priced_per_bond_its_percent_of_nominal_plus_its_accrued_interest() -> None:
    quote = BossaSource(SavedBossa(), ACH0427).quote("ACH0427", "PLN")

    assert quote == Quote(Decimal("1012.93"), "PLN", FRIDAY, BOSSA)  # 101,00 % of 1000 zł + 2,93 zł


def test_an_iz_bond_is_priced_at_its_indexed_nominal_of_the_quotes_day_from_gov_pl() -> None:
    def pages(url: str) -> str:
        return CATALYST_PAGES[url].read_text(encoding="utf-8")

    facts = CatalystFacts(pages)

    # 96,50 % of 1075,72 zł (1000 zł × 1,07572 on Friday 02.10.2026, the Quote's day) + 1,96 zł
    assert BossaSource(SavedBossa(), facts).quote("IZ0831", "PLN").price == Decimal("1040.0298")


def test_a_catalyst_bond_without_its_nominal_is_an_error_not_a_percent() -> None:
    with pytest.raises(PriceSourceError, match="gpwcatalyst.pl"):
        BossaSource(SavedBossa(), FixedFacts({})).quote("ACH0427", "PLN")


def test_a_new_refresh_also_fetches_the_bond_facts_anew() -> None:
    facts = FixedFacts({})

    BossaSource(SavedBossa(), facts).new_refresh()

    assert facts.refreshes == 1


def test_one_request_per_category_whatever_the_number_of_instruments() -> None:
    fetch = SavedBossa()
    source = BossaSource(fetch, ACH0427)

    for symbol in ("PZU", "CDR", "11B", "ONE", "BGD", "ACH0427", "ETFBDIVPL"):
        source.quote(symbol, "PLN")

    assert sorted(fetch.asked) == ["_cat_bonds", "_cat_etf", "_cat_nConnect", "_cat_shares"]


def test_only_the_categories_needed_are_requested() -> None:
    fetch = SavedBossa()

    BossaSource(fetch).quote("PZU", "PLN")

    assert fetch.asked == ["_cat_shares"]


def test_a_new_refresh_requests_the_categories_again() -> None:
    fetch = SavedBossa()
    source = BossaSource(fetch)
    source.quote("PZU", "PLN")

    source.new_refresh()
    source.quote("PZU", "PLN")

    assert fetch.asked == ["_cat_shares", "_cat_shares"]


def test_an_unknown_symbol_is_an_error() -> None:
    with pytest.raises(PriceSourceError, match="Bossa nie zna symbolu „XYZ”"):
        BossaSource(SavedBossa()).quote("XYZ", "PLN")


def test_an_instrument_quoted_in_another_currency_is_an_error_carrying_bossas_quote() -> None:
    with pytest.raises(CurrencyMismatchError, match="PLN.*USD") as raised:
        BossaSource(SavedBossa()).quote("PZU", "USD")

    assert raised.value.quote == Quote(Decimal("69.8200"), "PLN", date(2026, 10, 2), BOSSA)


def test_an_instrument_in_another_currency_is_a_currency_error_even_when_bossa_does_not_know_the_symbol() -> None:
    with pytest.raises(PriceSourceError, match="PLN.*USD") as raised:
        BossaSource(SavedBossa()).quote("XYZ", "USD")

    assert not isinstance(raised.value, CurrencyMismatchError)


def test_without_a_connection_the_error_says_so() -> None:
    fetch = SavedBossa({"_cat_shares": URLError("offline")})

    with pytest.raises(PriceSourceError, match="Nie udało się połączyć z Bossa"):
        BossaSource(fetch).quote("PZU", "PLN")


def test_a_category_that_failed_is_not_requested_again_in_the_same_refresh() -> None:
    error = HTTPError("url", 503, "Service Unavailable", Message(), None)
    fetch = SavedBossa({"_cat_shares": error})
    source = BossaSource(fetch)
    for symbol in ("PZU", "CDR"):
        with pytest.raises(PriceSourceError, match="HTTP 503"):
            source.quote(symbol, "PLN")

    assert fetch.asked.count("_cat_shares") == 1


def test_a_category_that_failed_is_requested_again_in_the_next_refresh() -> None:
    fetch = SavedBossa({"_cat_shares": URLError("offline")})
    source = BossaSource(fetch)
    with pytest.raises(PriceSourceError):
        source.quote("PZU", "PLN")

    fetch.failing.clear()
    source.new_refresh()

    assert source.quote("PZU", "PLN").price == Decimal("69.8200")


def test_a_symbol_found_in_a_later_category_is_quoted_even_when_an_earlier_one_failed() -> None:
    fetch = SavedBossa({"_cat_shares": URLError("offline")})

    assert BossaSource(fetch).quote("ETFBDIVPL", "PLN").price == Decimal("297.7500")


def test_a_malformed_response_is_an_error() -> None:
    with pytest.raises(PriceSourceError, match="Nieprawidłowa odpowiedź Bossa"):
        BossaSource(lambda url: "<html>").quote("PZU", "PLN")


def test_a_listing_without_a_usable_price_or_day_is_skipped_and_the_others_still_quoted() -> None:
    body = json.dumps(
        {
            "_d": [
                {
                    "_t": [
                        {
                            "_symbol": "ZERO",
                            "_symbol_short": "ZER",
                            "_quote": "0.0000",
                            "_quote_ref": None,
                            "_quote_date": "2026.10.02",
                        },
                        {
                            "_symbol": "NODAY",
                            "_symbol_short": "NDY",
                            "_quote": "5.0000",
                            "_quote_ref": None,
                            "_quote_date": None,
                        },
                        {
                            "_symbol": "PZU",
                            "_symbol_short": "PZU",
                            "_quote": "69.8200",
                            "_quote_ref": "70.1400",
                            "_quote_date": "2026.10.02",
                        },
                    ]
                }
            ]
        }
    )
    source = BossaSource(lambda url: body)

    assert source.quote("PZU", "PLN").price == Decimal("69.8200")
    for symbol in ("ZER", "NDY"):
        with pytest.raises(PriceSourceError, match="nie zna symbolu"):
            source.quote(symbol, "PLN")
