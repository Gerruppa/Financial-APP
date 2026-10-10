"""Price history from Stooq (issue #33, spec 4.1), on saved responses without the network.

``wig.csv`` and ``cdr.csv`` follow Stooq's documented CSV layout (stooq.com English and stooq.pl Polish headers);
their prices are illustrative. ``challenge.html`` is the browser check Stooq puts in front of every request.
"""

import hashlib
from datetime import date
from decimal import Decimal
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from financial_app.domain.prices import STOOQ, PriceSourceError, Quote
from financial_app.sources.stooq import StooqSource, answer_challenge

FIXTURES = Path(__file__).parent / "fixtures" / "stooq"
JAN_2 = date(2026, 1, 2)
JAN_9 = date(2026, 1, 9)


class SavedStooq:
    """Answers with the saved CSV for the symbol in the URL, or with ``body``; records the URLs."""

    def __init__(self, body: str | None = None) -> None:
        self.body = body
        self.requests: list[str] = []

    def __call__(self, url: str) -> str:
        self.requests.append(url)
        if self.body is not None:
            return self.body
        symbol = url.split("s=", 1)[1].split("&", 1)[0]
        return (FIXTURES / f"{symbol}.csv").read_text(encoding="utf-8")


def test_an_index_history_is_its_daily_closes_in_the_instruments_currency() -> None:
    stooq = SavedStooq()

    quotes = StooqSource("KEY", stooq).history("WIG", "PLN", JAN_2, JAN_9)

    assert quotes[0] == Quote(Decimal("118702.33"), "PLN", JAN_2, STOOQ)
    assert [q.day.day for q in quotes] == [2, 5, 7, 8, 9]
    assert stooq.requests == ["https://stooq.com/q/d/l/?s=wig&d1=20260102&d2=20260109&i=d&apikey=KEY"]


def test_polish_headers_are_read_too() -> None:
    quotes = StooqSource("KEY", SavedStooq()).history("cdr", "PLN", JAN_2, JAN_9)

    assert quotes == [
        Quote(Decimal("264.1"), "PLN", JAN_2, STOOQ),
        Quote(Decimal("268.2"), "PLN", date(2026, 1, 5), STOOQ),
    ]


@pytest.mark.parametrize("answer", ["Brak danych", "No data\n"])
def test_a_range_without_trading_has_no_quotes(answer: str) -> None:
    assert StooqSource("KEY", SavedStooq(answer)).history("wig", "PLN", JAN_2, JAN_2) == []


def test_without_an_api_key_nothing_is_asked() -> None:
    stooq = SavedStooq()

    with pytest.raises(PriceSourceError, match="Brak klucza API Stooq"):
        StooqSource(" ", stooq).history("wig", "PLN", JAN_2, JAN_9)
    assert stooq.requests == []


@pytest.mark.parametrize("answer", ["Access denied", "Odmowa dostępu"])
def test_a_refused_key_is_reported(answer: str) -> None:
    with pytest.raises(PriceSourceError, match="Sprawdź klucz API Stooq"):
        StooqSource("KEY", SavedStooq(answer)).history("wig", "PLN", JAN_2, JAN_9)


@pytest.mark.parametrize("answer", ["Exceeded the daily hits limit", "Przekroczony dzienny limit wywolan"])
def test_the_daily_limit_is_reported(answer: str) -> None:
    with pytest.raises(PriceSourceError, match="dzienny limit"):
        StooqSource("KEY", SavedStooq(answer)).history("wig", "PLN", JAN_2, JAN_9)


def test_an_unexpected_page_is_reported() -> None:
    page = (FIXTURES / "challenge.html").read_text(encoding="utf-8")

    with pytest.raises(PriceSourceError, match="Nieprawidłowa odpowiedź Stooq"):
        StooqSource("KEY", SavedStooq(page)).history("wig", "PLN", JAN_2, JAN_9)


def test_network_failures_are_reported() -> None:
    def offline(url: str) -> str:
        raise URLError("offline")

    def server_error(url: str) -> str:
        raise HTTPError(url, 503, "Service Unavailable", Message(), None)

    with pytest.raises(PriceSourceError, match="Nie udało się połączyć ze Stooq"):
        StooqSource("KEY", offline).history("wig", "PLN", JAN_2, JAN_9)
    with pytest.raises(PriceSourceError, match="HTTP 503"):
        StooqSource("KEY", server_error).history("wig", "PLN", JAN_2, JAN_9)


def test_the_browser_check_is_answered_like_a_browser_does() -> None:
    page = (FIXTURES / "challenge.html").read_text(encoding="utf-8")

    answer = answer_challenge(page)

    assert answer is not None
    challenge, nonce = answer
    assert challenge.startswith("AAAAA")
    # The page asks for a SHA-256 of the challenge and a number starting with four hex zeros
    assert hashlib.sha256(f"{challenge}{nonce}".encode()).hexdigest().startswith("0000")


def test_a_csv_is_not_a_browser_check() -> None:
    assert answer_challenge((FIXTURES / "wig.csv").read_text(encoding="utf-8")) is None
