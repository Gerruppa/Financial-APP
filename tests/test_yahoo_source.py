"""Quotes from the Yahoo chart API (issue #30, spec 4.1), on saved responses without the network."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote

import pytest

from financial_app.domain.prices import PriceSourceError, Quote
from financial_app.sources.yahoo import YahooSource

FIXTURES = Path(__file__).parent / "fixtures" / "yahoo"


def _saved(url: str) -> str | None:
    """The saved response for the symbol in ``url``; None (HTTP 404) for a symbol without one."""
    symbol = unquote(url.split("/chart/")[1].split("?")[0])
    path = FIXTURES / f"{symbol}.json"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def test_a_quote_has_the_price_currency_and_the_exchange_day() -> None:
    quote = YahooSource(_saved).quote("AAPL", "USD")

    # 00:30 UTC on 10 October is still 9 October in New York
    assert quote == Quote(Decimal("254.63"), "USD", date(2026, 10, 9), "yahoo")


def test_a_price_in_pence_is_stored_in_pounds() -> None:
    quote = YahooSource(_saved).quote("BP.L", "GBP")

    assert quote == Quote(Decimal("5.863"), "GBP", date(2026, 10, 9), "yahoo")


def test_a_price_in_another_currency_than_the_instruments_is_an_error() -> None:
    with pytest.raises(PriceSourceError, match="USD.*GBP"):
        YahooSource(_saved).quote("ISAC.L", "GBP")


def test_crypto_in_usd_for_a_pln_instrument_is_converted_at_yahoos_usd_rate() -> None:
    quote = YahooSource(_saved).quote("BTC-USD", "PLN")

    # 92 514,37 USD at USDPLN=X 3,9087
    assert quote == Quote(Decimal("361610.918019"), "PLN", date(2026, 10, 10), "yahoo")


def test_an_unknown_symbol_is_an_error_naming_it() -> None:
    with pytest.raises(PriceSourceError, match="Yahoo nie zna symbolu „NOSUCH”"):
        YahooSource(_saved).quote("NOSUCH", "USD")


def _offline(url: str) -> str | None:
    raise URLError("no network")


def _too_many_requests(url: str) -> str | None:
    raise HTTPError(url, 429, "Too Many Requests", Message(), None)


@pytest.mark.parametrize(
    ("fetch", "message"),
    [
        (_offline, "Nie udało się połączyć z Yahoo"),
        (_too_many_requests, "Yahoo zwróciło błąd HTTP 429"),
        (lambda url: '{"chart": {"result": []}}', "Nieprawidłowa odpowiedź Yahoo dla AAPL"),
        (lambda url: "<html>", "Nieprawidłowa odpowiedź Yahoo dla AAPL"),
    ],
)
def test_a_failed_fetch_is_an_error_saying_why(fetch: Callable[[str], str | None], message: str) -> None:
    with pytest.raises(PriceSourceError, match=message):
        YahooSource(fetch).quote("AAPL", "USD")
