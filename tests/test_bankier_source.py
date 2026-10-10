"""Fund and PPK Quotes from bankier.pl's fund pages (issue #32, spec 4.1), on saved pages without the network."""

from datetime import date
from decimal import Decimal
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from financial_app.domain.prices import BANKIER, PriceSourceError, Quote
from financial_app.sources.bankier import BankierSource

FIXTURES = Path(__file__).parent / "fixtures" / "bankier"
# bankier.pl sends an unknown fund to its home page, which has quotes but no fund's header
HOME_PAGE = '<html><body><span class="a-quote-item -value">2 345,67 PLN</span></body></html>'


class SavedBankier:
    """Answers each fund page from its saved copy, the home page for the others, and records the pages asked for."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def __call__(self, url: str) -> str | None:
        kind, symbol = url.removeprefix("https://www.bankier.pl/").split("/notowania/")
        self.asked.append(f"{kind}/{symbol}")
        path = FIXTURES / f"{kind}_{symbol}.html"
        return path.read_text(encoding="utf-8") if path.is_file() else HOME_PAGE


def test_a_fund_is_quoted_from_its_page_with_its_valuation_day() -> None:
    quote = BankierSource(SavedBankier()).quote("QRS32", "PLN")

    assert quote == Quote(Decimal("203.83"), "PLN", date(2026, 10, 8), BANKIER)


def test_a_ppk_fund_is_quoted_from_the_ppk_page_when_the_fund_pages_do_not_have_it() -> None:
    fetch = SavedBankier()

    quote = BankierSource(fetch).quote("pzu60", "PLN")

    assert quote == Quote(Decimal("118.49"), "PLN", date(2026, 10, 8), BANKIER)
    assert fetch.asked == ["fundusze/PZU60", "ppk/PZU60"]


def test_a_fund_found_on_the_fund_pages_is_not_looked_for_among_ppk() -> None:
    fetch = SavedBankier()

    BankierSource(fetch).quote("QRS32", "PLN")

    assert fetch.asked == ["fundusze/QRS32"]


def test_an_unknown_fund_is_an_error_naming_it() -> None:
    with pytest.raises(PriceSourceError, match="bankier.pl nie zna funduszu „NOSUCH99”"):
        BankierSource(SavedBankier()).quote("NOSUCH99", "PLN")


def test_a_page_not_found_is_an_unknown_fund_too() -> None:
    with pytest.raises(PriceSourceError, match="nie zna funduszu"):
        BankierSource(lambda url: None).quote("QRS32", "PLN")


def test_a_fund_valued_in_another_currency_than_the_instruments_is_an_error() -> None:
    with pytest.raises(PriceSourceError, match="PLN.*EUR"):
        BankierSource(SavedBankier()).quote("QRS32", "EUR")


def test_a_price_with_thousands_separators_is_read() -> None:
    page = (FIXTURES / "fundusze_QRS32.html").read_text(encoding="utf-8").replace(">203,83", ">1\xa0203,83")

    assert BankierSource(lambda url: page).quote("QRS32", "PLN").price == Decimal("1203.83")


def test_a_fund_page_without_a_price_or_day_is_an_error() -> None:
    page = (FIXTURES / "fundusze_QRS32.html").read_text(encoding="utf-8").replace("08.10.2026", "")

    with pytest.raises(PriceSourceError, match="Nieprawidłowa odpowiedź bankier.pl"):
        BankierSource(lambda url: page).quote("QRS32", "PLN")


def test_without_a_connection_the_error_says_so() -> None:
    def offline(url: str) -> str | None:
        raise URLError("no network")

    with pytest.raises(PriceSourceError, match="Nie udało się połączyć z bankier.pl"):
        BankierSource(offline).quote("QRS32", "PLN")


def test_an_http_error_names_its_code() -> None:
    def unavailable(url: str) -> str | None:
        raise HTTPError(url, 503, "Service Unavailable", Message(), None)

    with pytest.raises(PriceSourceError, match="HTTP 503"):
        BankierSource(unavailable).quote("QRS32", "PLN")
