"""NBP Rates (D-1) from the NBP API, table A (spec section 4), through the local cache."""

import json
import time
import urllib.request
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from urllib.error import HTTPError

from sqlalchemy import Engine

from financial_app.domain.currencies import MissingNbpRateError, NbpRate
from financial_app.domain.formatting import format_date
from financial_app.domain.history import ONE_DAY, Cover, days_to_fetch
from financial_app.persistence.history import nbp_history_cover, nbp_rates_between, save_nbp_history
from financial_app.persistence.nbp_rates import cache_rate, cached_rate

API = "https://api.nbp.pl/api/exchangerates/rates/a/{currency}/{start:%Y-%m-%d}/{end:%Y-%m-%d}/?format=json"
# The longest run of days without a table (Christmas plus a weekend) is far shorter
LOOKBACK = timedelta(days=14)
RETRY_AFTER = 300  # seconds
# The NBP API answers at most this many days of rates at once, and has table A from this day on
MAX_DAYS = 93
FIRST_TABLE = date(2002, 1, 2)


def fetch_from_nbp(url: str) -> str | None:
    """The response body, or None when the NBP has no data (HTTP 404); network failures raise OSError."""
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            body: bytes = response.read()
            return body.decode("utf-8")
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


class NbpRates:
    """The NBP Rate (D-1) for a Transaction day; each one is fetched once, then read from the cache."""

    def __init__(
        self,
        engine: Engine,
        fetch: Callable[[str], str | None] = fetch_from_nbp,
        today: Callable[[], date] = date.today,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.engine = engine
        self.fetch = fetch
        self.today = today
        self.clock = clock
        self._failed_at: dict[str, float] = {}

    def before(self, currency: str, day: date) -> NbpRate:
        """The table A mid rate from the last business day before ``day``; raises MissingNbpRateError if unknown."""
        currency = currency.upper()
        if (cached := cached_rate(self.engine, currency, day)) is not None:
            return cached
        today = self.today()
        if day > today + ONE_DAY:
            raise _not_published_yet(currency, day)
        rate = self._fetch_latest(currency, start=day - LOOKBACK, end=min(day - ONE_DAY, today), day=day)
        # For tomorrow, only today's table is surely the right one; an earlier one may still be superseded today
        if day > today and rate.published_on != today:
            raise _not_published_yet(currency, day)
        cache_rate(self.engine, day, rate)
        return rate

    def latest(self, currency: str) -> NbpRate:
        """The NBP Rate from the last business day before today, for valuing foreign Positions.

        A stopgap until automatic valuation with current FX rates (issue #3). After a failed fetch it does not try
        again for RETRY_AFTER seconds, so that the Portfolio does not wait for the network on every redraw.
        """
        currency = currency.upper()
        failed_at = self._failed_at.get(currency)
        if failed_at is not None and self.clock() - failed_at < RETRY_AFTER:
            raise MissingNbpRateError(f"Brak kursu NBP {currency}.")
        try:
            return self.before(currency, self.today())
        except MissingNbpRateError:
            self._failed_at[currency] = self.clock()
            raise

    def history(self, currency: str, first: date, last: date) -> list[NbpRate]:
        """The NBP Rates of ``currency`` published from ``first`` to ``last``, oldest first, for History (#33).

        Days not fetched yet are fetched once, up to yesterday (today's table may not be out yet), then read from
        the cache. A failed fetch raises ``MissingNbpRateError`` and is tried again next time.
        """
        currency = currency.upper()
        missing = days_to_fetch(
            nbp_history_cover(self.engine, currency), max(first, FIRST_TABLE), min(last, self.today() - ONE_DAY)
        )
        for days in missing:
            rates = [rate for piece in days.split(MAX_DAYS) for rate in self._fetch_range(currency, piece)]
            save_nbp_history(self.engine, currency, rates, days)
        return nbp_rates_between(self.engine, currency, first, last)

    def _fetch_range(self, currency: str, days: Cover) -> list[NbpRate]:
        """The rates the NBP published in ``days``; none when it published no table then (HTTP 404)."""
        period = f"{currency} z okresu {format_date(days.first)}–{format_date(days.last)}"
        try:
            body = self.fetch(API.format(currency=currency.lower(), start=days.first, end=days.last))
        except HTTPError:
            raise MissingNbpRateError(f"Serwis NBP zwrócił błąd przy pobieraniu kursów {period}.") from None
        except OSError:
            raise MissingNbpRateError(
                f"Nie udało się pobrać kursów NBP {period}. Sprawdź połączenie z internetem."
            ) from None
        if body is None:
            return []
        try:
            return _parse_rates(body, currency)
        except ValueError, KeyError, TypeError:
            raise MissingNbpRateError(f"Nieprawidłowa odpowiedź NBP dla kursów {period}.") from None

    def _fetch_latest(self, currency: str, start: date, end: date, day: date) -> NbpRate:
        """The last rate the NBP published between ``start`` and ``end``; ``day`` is only for the messages."""
        before = f"{currency} sprzed {format_date(day)}"
        try:
            body = self.fetch(API.format(currency=currency.lower(), start=start, end=end))
        except HTTPError:
            raise MissingNbpRateError(
                f"Serwis NBP zwrócił błąd przy pobieraniu kursu {before}. Spróbuj później. Zapis zablokowany."
            ) from None
        except OSError:
            raise MissingNbpRateError(
                f"Nie udało się pobrać kursu NBP {before}. Sprawdź połączenie z internetem. Zapis zablokowany."
            ) from None
        if body is None:
            raise MissingNbpRateError(f"Brak kursu NBP {before}. Zapis zablokowany.")
        try:
            return _parse_rates(body, currency)[-1]
        except ValueError, KeyError, IndexError, TypeError:
            raise MissingNbpRateError(f"Nieprawidłowa odpowiedź NBP dla kursu {before}. Zapis zablokowany.") from None


def _parse_rates(body: str, currency: str) -> list[NbpRate]:
    """The rates in an NBP API answer, in the order given (oldest first)."""
    return [
        NbpRate(currency, published["mid"], date.fromisoformat(published["effectiveDate"]), published["no"])
        for published in json.loads(body, parse_float=Decimal)["rates"]
    ]


def _not_published_yet(currency: str, day: date) -> MissingNbpRateError:
    return MissingNbpRateError(
        f"Kurs NBP {currency} sprzed {format_date(day)} nie został jeszcze opublikowany. Zapis zablokowany."
    )
