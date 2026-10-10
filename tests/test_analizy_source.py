"""Fund and PPK Quotes from the analizy.pl API (issue #32, spec 4.1), on saved responses without the network."""

from datetime import date
from decimal import Decimal
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from financial_app.domain.prices import ANALIZY, PriceSourceError, Quote
from financial_app.sources.analizy import AnalizySource

FIXTURES = Path(__file__).parent / "fixtures" / "analizy"


def _saved(url: str) -> str | None:
    """The saved response for the fund id in ``url``; None (HTTP 404) for an id without one."""
    path = FIXTURES / f"{url.rsplit('/', 1)[1]}.json"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def test_a_fund_is_quoted_at_its_newest_valuation_with_its_day() -> None:
    # Funds are valued once a day, so the newest valuation is often from the day before
    assert AnalizySource(_saved).quote("PZU60", "PLN") == Quote(Decimal("118.49"), "PLN", date(2026, 10, 8), ANALIZY)


def test_the_id_is_found_in_any_case_and_with_spaces_around_it() -> None:
    asked: list[str] = []

    def fetch(url: str) -> str | None:
        asked.append(url)
        return _saved(url)

    assert AnalizySource(fetch).quote(" pzu60 ", "PLN").price == Decimal("118.49")
    assert asked == ["https://www.analizy.pl/api/quotation/fio/PZU60"]


def test_a_foreign_fund_is_quoted_in_its_own_currency() -> None:
    quote = AnalizySource(_saved).quote("FTI068_AH_EUR", "EUR")

    assert quote == Quote(Decimal("13.65"), "EUR", date(2026, 10, 9), ANALIZY)


def test_a_fund_valued_in_another_currency_than_the_instruments_is_an_error() -> None:
    with pytest.raises(PriceSourceError, match="EUR.*PLN"):
        AnalizySource(_saved).quote("FTI068_AH_EUR", "PLN")


def test_an_unknown_id_is_an_error_naming_it() -> None:
    with pytest.raises(PriceSourceError, match="analizy.pl nie zna funduszu „NOSUCH99”"):
        AnalizySource(_saved).quote("NOSUCH99", "PLN")


def test_a_fund_without_valuations_is_an_error() -> None:
    body = '{"id": "NEW1", "currency": "PLN", "series": [{"id": "fund_NEW1", "price": []}]}'

    with pytest.raises(PriceSourceError, match="analizy.pl nie ma wyceny funduszu „NEW1”"):
        AnalizySource(lambda url: body).quote("NEW1", "PLN")


def test_without_a_connection_the_error_says_so() -> None:
    def offline(url: str) -> str | None:
        raise URLError("no network")

    with pytest.raises(PriceSourceError, match="Nie udało się połączyć z analizy.pl"):
        AnalizySource(offline).quote("PZU60", "PLN")


def test_an_http_error_names_its_code() -> None:
    def unavailable(url: str) -> str | None:
        raise HTTPError(url, 503, "Service Unavailable", Message(), None)

    with pytest.raises(PriceSourceError, match="HTTP 503"):
        AnalizySource(unavailable).quote("PZU60", "PLN")


@pytest.mark.parametrize("body", ["<html>", '{"series": []}', '{"currency": "PLN", "series": [{"price": [{}]}]}'])
def test_a_malformed_response_is_an_error(body: str) -> None:
    with pytest.raises(PriceSourceError, match="Nieprawidłowa odpowiedź analizy.pl"):
        AnalizySource(lambda url: body).quote("PZU60", "PLN")
