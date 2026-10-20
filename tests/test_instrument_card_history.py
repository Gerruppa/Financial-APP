"""The Instrument Card's price history (issue #175), fetched live from Yahoo or analizy.pl, on saved responses."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

from financial_app.domain.instrument_search import FoundListing
from financial_app.domain.prices import ANALIZY, BOSSA, YAHOO, PriceSourceError
from financial_app.sources.instrument_card import CardHistory

FIXTURES = Path(__file__).parent / "fixtures"


def _yahoo(url: str) -> str | None:
    path = FIXTURES / "yahoo" / "history" / f"{unquote(urlparse(url).path.split('/chart/')[1])}.json"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _analizy(url: str) -> str | None:
    path = FIXTURES / "analizy" / "history" / f"{url.rsplit('/', 1)[1]}.json"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _not_asked(url: str) -> str | None:
    raise AssertionError(f"asked: {url}")


def _listing(source_symbols: dict[str, str], currency: str) -> FoundListing:
    return FoundListing("Listing", "", "", currency, source_symbols)


def test_a_listing_with_a_yahoo_symbol_takes_its_whole_history_from_yahoo() -> None:
    history = CardHistory(yahoo_fetch=_yahoo, analizy_fetch=_not_asked)

    quotes = history.closes(_listing({YAHOO: "BP.L", BOSSA: "BP"}, "GBP"), date(2026, 1, 6))

    assert [(q.day, q.price) for q in quotes][-2:] == [
        (date(2026, 1, 2), Decimal("5.805")),
        (date(2026, 1, 6), Decimal("5.9")),
    ]


def test_a_fund_without_a_yahoo_symbol_takes_its_history_from_analizy() -> None:
    history = CardHistory(yahoo_fetch=_not_asked, analizy_fetch=_analizy)

    quotes = history.closes(_listing({ANALIZY: "PZU01"}, "PLN"), date(2026, 1, 7))

    assert [(q.day, q.price) for q in quotes][-3:] == [
        (date(2026, 1, 2), Decimal("136.24")),
        (date(2026, 1, 5), Decimal("137.06")),
        (date(2026, 1, 7), Decimal("139.68")),
    ]


def test_without_a_yahoo_or_analizy_symbol_there_is_no_history_to_show() -> None:
    history = CardHistory(yahoo_fetch=_not_asked, analizy_fetch=_not_asked)

    assert history.closes(_listing({BOSSA: "CDR"}, "PLN"), date(2026, 1, 7)) == []


def test_an_unknown_currency_cannot_be_checked_so_gives_an_error_in_polish() -> None:
    history = CardHistory(yahoo_fetch=_not_asked, analizy_fetch=_not_asked)

    with pytest.raises(PriceSourceError, match="Nie wiadomo, w jakiej walucie"):
        history.closes(_listing({YAHOO: "BP.L"}, ""), date(2026, 1, 6))
