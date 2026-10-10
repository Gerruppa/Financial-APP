"""Price history of GPW Instruments and indices (WIG, sWIG80TR) from Stooq (issue #33, spec 4.1, ADR-0005).

Stooq serves history only, never the current price. Its CSV download needs the user's personal API key (Ustawienia),
and every request first meets a browser check: a small proof of work that ``fetch_from_stooq`` answers the way the
page's own script does, keeping the cookie it earns for the following requests.
"""

import csv
import hashlib
import http.cookiejar
import io
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError

from financial_app.domain.prices import STOOQ, PriceSourceError, Quote

SITE = "https://stooq.com"
API = SITE + "/q/d/l/?s={symbol}&d1={first:%Y%m%d}&d2={last:%Y%m%d}&i=d&apikey={key}"
_CHALLENGE = re.compile(r'const c="([^"]+)",d=(\d+)')

_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
_opener.addheaders = [("User-Agent", "Mozilla/5.0")]


def answer_challenge(page: str) -> tuple[str, int] | None:
    """The answer to Stooq's browser check on ``page``: its challenge and the first number whose SHA-256 together
    with it starts with the asked number of hex zeros; ``None`` when ``page`` is no check."""
    found = _CHALLENGE.search(page)
    if found is None:
        return None
    challenge, zeros = found.group(1), "0" * int(found.group(2))
    nonce = 0
    while not hashlib.sha256(f"{challenge}{nonce}".encode()).hexdigest().startswith(zeros):
        nonce += 1
    return challenge, nonce


def fetch_from_stooq(url: str) -> str:
    """The response body, after answering the browser check once if Stooq asks; network failures raise OSError."""
    body = _get(url)
    if (answer := answer_challenge(body)) is not None:
        form = urllib.parse.urlencode({"c": answer[0], "n": answer[1]}).encode()
        with _opener.open(SITE + "/__verify", data=form, timeout=15):
            pass
        body = _get(url)
    return body


def _get(url: str) -> str:
    with _opener.open(url, timeout=30) as response:
        content: bytes = response.read()
        return content.decode("utf-8", errors="replace")


class StooqSource:
    """Stooq with the user's API key; ``fetch`` is injectable so tests run on saved responses."""

    name = STOOQ

    def __init__(self, api_key: str, fetch: Callable[[str], str] = fetch_from_stooq) -> None:
        self.api_key = api_key.strip()
        self.fetch = fetch

    def history(self, symbol: str, currency: str, first: date, last: date) -> list[Quote]:
        """The daily closes of ``symbol`` (e.g. wig, cdr) from ``first`` to ``last``, oldest first.

        Stooq's CSV names no currency, so the closes are taken as in ``currency``, the Instrument's quote currency
        (an index's points as PLN). A range without trading has no Quotes.
        """
        if not self.api_key:
            raise PriceSourceError("Brak klucza API Stooq. Wpisz go w Ustawieniach.")
        key = symbol.strip().lower()
        url = API.format(
            symbol=urllib.parse.quote(key, safe=""),
            first=first,
            last=last,
            key=urllib.parse.quote(self.api_key, safe=""),
        )
        try:
            body = self.fetch(url)
        except HTTPError as exc:
            raise PriceSourceError(f"Stooq zwrócił błąd HTTP {exc.code}. Spróbuj później.") from None
        except OSError:
            raise PriceSourceError("Nie udało się połączyć ze Stooq. Sprawdź połączenie z internetem.") from None
        return _closes(body.strip(), key, currency)


def _closes(body: str, symbol: str, currency: str) -> list[Quote]:
    message = body.casefold()
    if message in ("brak danych", "no data"):
        return []
    if message in ("access denied", "odmowa dostępu"):
        raise PriceSourceError("Stooq odmówił dostępu. Sprawdź klucz API Stooq w Ustawieniach.")
    if "limit" in message and "," not in message:
        raise PriceSourceError("Wyczerpano dzienny limit zapytań do Stooq. Spróbuj jutro.")
    rows = list(csv.reader(io.StringIO(body)))
    try:
        header = [column.strip().casefold() for column in rows[0]]
        day_column = header.index("date") if "date" in header else header.index("data")
        close_column = header.index("close") if "close" in header else header.index("zamkniecie")
        quotes = [
            Quote(Decimal(row[close_column]), currency, date.fromisoformat(row[day_column]), STOOQ)
            for row in rows[1:]
            if row
        ]
    except ValueError, IndexError, InvalidOperation:
        raise PriceSourceError(f"Nieprawidłowa odpowiedź Stooq dla „{symbol}”.") from None
    return sorted((quote for quote in quotes if quote.price > 0), key=lambda quote: quote.day)
