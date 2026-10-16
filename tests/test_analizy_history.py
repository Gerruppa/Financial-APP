"""Fund and PPK valuation history from analizy.pl for History (#101): the keyless source between Yahoo and Stooq, on
a saved, trimmed response without the network."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.prices import ANALIZY, ANALIZY_HISTORY, YAHOO, PriceSourceError, Quote
from financial_app.persistence.db import init_db
from financial_app.persistence.history import history_prices, quotes_between
from financial_app.persistence.instruments import add_asset_class, add_instrument, list_instruments, update_instrument
from financial_app.persistence.quotes import latest_quotes
from financial_app.sources.analizy import AnalizySource
from financial_app.sources.history import QuoteHistory

FIXTURES = Path(__file__).parent / "fixtures" / "analizy" / "history"
NOW = datetime(2026, 1, 12, 9, 30)
TODAY = date(2026, 1, 12)


def _saved(url: str) -> str | None:
    path = FIXTURES / f"{url.rsplit('/', 1)[1]}.json"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _no_stooq(url: str) -> str:
    raise AssertionError(f"Stooq asked: {url}")


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _fund(engine: Engine, symbols: dict[str, str], currency: str = "PLN") -> int:
    funds = add_asset_class(engine, "Fundusze")
    return add_instrument(engine, InstrumentDraft("PZU Akcji", funds.id, currency, source_symbols=symbols)).id


def test_the_history_is_the_funds_valuations_within_the_days() -> None:
    quotes = AnalizySource(_saved).history("pzu01", "PLN", date(2026, 1, 2), date(2026, 1, 7))

    assert quotes == [
        Quote(Decimal("136.24"), "PLN", date(2026, 1, 2), ANALIZY_HISTORY),
        Quote(Decimal("137.06"), "PLN", date(2026, 1, 5), ANALIZY_HISTORY),
        Quote(Decimal("139.68"), "PLN", date(2026, 1, 7), ANALIZY_HISTORY),
    ]


def test_a_fund_valued_in_another_currency_has_no_history() -> None:
    with pytest.raises(PriceSourceError, match="w PLN, a instrument jest notowany w EUR"):
        AnalizySource(_saved).history("PZU01", "EUR", date(2026, 1, 2), date(2026, 1, 7))


def test_an_unknown_fund_has_no_history() -> None:
    with pytest.raises(PriceSourceError, match="nie zna funduszu"):
        AnalizySource(_saved).history("XYZ99", "PLN", date(2026, 1, 2), date(2026, 1, 7))


def test_a_fund_without_yahoo_takes_its_history_from_analizy_and_never_as_its_current_price(engine: Engine) -> None:
    fund = _fund(engine, {ANALIZY: "PZU01"})
    history = QuoteHistory(engine, fetch=_no_stooq, today=lambda: TODAY, now=lambda: NOW, analizy_fetch=_saved)

    quotes = history.between(fund, date(2026, 1, 5), date(2026, 1, 9))

    assert [(q.day, q.price, q.source) for q in quotes] == [
        (date(2026, 1, 5), Decimal("137.06"), ANALIZY_HISTORY),
        (date(2026, 1, 7), Decimal("139.68"), ANALIZY_HISTORY),
        (date(2026, 1, 8), Decimal("137.48"), ANALIZY_HISTORY),
        (date(2026, 1, 9), Decimal("139.33"), ANALIZY_HISTORY),
    ]
    assert fund not in latest_quotes(engine)
    # Funds do not split, so their valuations are not rescaled by Splits
    assert all(price.adjusted_on is None for price in history_prices(engine, fund))


def test_yahoo_comes_before_analizy(engine: Engine) -> None:
    fund = _fund(engine, {YAHOO: "UNKNOWN", ANALIZY: "PZU01"})
    asked: list[str] = []

    def yahoo(url: str) -> str | None:
        asked.append(url)
        return None

    history = QuoteHistory(
        engine, fetch=_no_stooq, today=lambda: TODAY, now=lambda: NOW, yahoo_fetch=yahoo, analizy_fetch=_saved
    )

    assert [q.source for q in history.between(fund, date(2026, 1, 8), date(2026, 1, 9))] == [ANALIZY_HISTORY] * 2
    assert len(asked) == 1


def test_a_new_fund_code_drops_the_fetched_history(engine: Engine) -> None:
    fund = _fund(engine, {ANALIZY: "PZU01"})
    QuoteHistory(engine, fetch=_no_stooq, today=lambda: TODAY, now=lambda: NOW, analizy_fetch=_saved).between(
        fund, date(2026, 1, 5), date(2026, 1, 9)
    )
    funds = list_instruments(engine)[0].asset_class_id

    update_instrument(engine, fund, InstrumentDraft("PZU Akcji", funds, "PLN", source_symbols={ANALIZY: "PZU60"}))

    assert quotes_between(engine, fund, date(2026, 1, 5), date(2026, 1, 9)) == []


def test_a_yahoo_listing_without_closes_leaves_the_days_to_analizy(engine: Engine) -> None:
    fund = _fund(engine, {YAHOO: "0P0000XYZ.F", ANALIZY: "PZU01"})
    empty = '{"chart": {"result": [{"meta": {"currency": "PLN", "gmtoffset": 3600}, "indicators": {"quote": [{}]}}]}}'
    history = QuoteHistory(
        engine,
        fetch=_no_stooq,
        today=lambda: TODAY,
        now=lambda: NOW,
        yahoo_fetch=lambda url: empty,
        analizy_fetch=_saved,
    )

    assert [q.source for q in history.between(fund, date(2026, 1, 8), date(2026, 1, 9))] == [ANALIZY_HISTORY] * 2


def test_analizy_is_asked_once_for_every_range_of_a_call(engine: Engine) -> None:
    fund = _fund(engine, {ANALIZY: "PZU01"})
    asked: list[str] = []

    def analizy(url: str) -> str | None:
        asked.append(url)
        return _saved(url)

    history = QuoteHistory(engine, fetch=_no_stooq, today=lambda: TODAY, now=lambda: NOW, analizy_fetch=analizy)
    history.between(fund, date(2026, 1, 5), date(2026, 1, 7))
    asked.clear()

    # Days before and after the fetched ones
    history.between(fund, date(2025, 12, 29), date(2026, 1, 9))

    assert len(asked) == 1
