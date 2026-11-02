"""A server certificate Windows does not trust is reported as such by every source that downloads, not as a missing
connection (issue #309); NBP and the bond data have theirs in test_nbp_rates.py and test_bond_data.py."""

import ssl
from collections.abc import Callable
from datetime import date
from typing import NoReturn
from urllib.error import URLError

import pytest

from financial_app.domain.app_update import UpdateError
from financial_app.domain.instrument_search import InstrumentSearchError
from financial_app.domain.prices import PriceSourceError
from financial_app.sources.analizy import AnalizySearch, AnalizySource
from financial_app.sources.app_update import UpdateSource
from financial_app.sources.bankier import BankierSource
from financial_app.sources.bossa import BossaSource
from financial_app.sources.catalyst import CatalystFacts
from financial_app.sources.stooq import StooqSource
from financial_app.sources.yahoo import YahooSearch, YahooSource

type Fetch = Callable[[str], NoReturn]
FAILURES = (PriceSourceError, InstrumentSearchError, UpdateError)


def _untrusted(url: str) -> NoReturn:
    raise URLError(ssl.SSLCertVerificationError(1, "certificate verify failed: unable to get local issuer"))


def _offline(url: str) -> NoReturn:
    raise URLError("offline")


ASKS: dict[str, Callable[[Fetch], object]] = {
    "GitHub update check": lambda fetch: UpdateSource(fetch).latest(),
    "Yahoo": lambda fetch: YahooSource(fetch).quote("AAPL", "USD"),
    "Yahoo search": lambda fetch: YahooSearch(fetch).search("ISAC"),
    "Stooq": lambda fetch: StooqSource("KEY", fetch).history("wig", "PLN", date(2026, 1, 2), date(2026, 1, 9)),
    "Bossa": lambda fetch: BossaSource(fetch).quote("PZU", "PLN"),
    "bankier.pl": lambda fetch: BankierSource(fetch).quote("QRS32", "PLN"),
    "analizy.pl": lambda fetch: AnalizySource(fetch).quote("PZU60", "PLN"),
    "analizy.pl search": lambda fetch: AnalizySearch(fetch).search("Quercus"),
    "gpwcatalyst.pl": lambda fetch: CatalystFacts(fetch).of("ACH0427", date(2026, 1, 9)),
}


@pytest.mark.parametrize("ask", ASKS.values(), ids=ASKS.keys())
def test_an_untrusted_certificate_is_named_instead_of_the_connection(ask: Callable[[Fetch], object]) -> None:
    with pytest.raises(FAILURES) as raised:
        ask(_untrusted)

    assert "certyfikat" in str(raised.value)
    assert "połączenie z internetem" not in str(raised.value)


@pytest.mark.parametrize("ask", ASKS.values(), ids=ASKS.keys())
def test_without_a_connection_the_advice_stays_to_check_it(ask: Callable[[Fetch], object]) -> None:
    with pytest.raises(FAILURES) as raised:
        ask(_offline)

    assert "Sprawdź połączenie z internetem" in str(raised.value)
