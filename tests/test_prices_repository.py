"""Saving Source Symbols and Quotes in SQLite (issue #30, spec 4.1)."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.prices import YAHOO, Quote
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, delete_instrument, list_instruments, update_instrument
from financial_app.persistence.quotes import latest_quotes, save_quote

FETCHED = datetime(2026, 10, 9, 18, 5)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def test_an_instruments_source_symbols_are_saved_with_it(engine: Engine) -> None:
    saved = add_instrument(engine, InstrumentDraft("ISAC", 3, "USD", "LSE", source_symbols={YAHOO: "ISAC.L"}))

    assert saved.source_symbols == {YAHOO: "ISAC.L"}
    assert list_instruments(engine)[0].source_symbols == {YAHOO: "ISAC.L"}


def test_editing_an_instrument_replaces_its_source_symbols(engine: Engine) -> None:
    saved = add_instrument(engine, InstrumentDraft("ISAC", 3, "USD", "LSE", source_symbols={YAHOO: "ISAC.L"}))

    update_instrument(engine, saved.id, InstrumentDraft("ISAC", 3, "USD", "LSE"))

    assert list_instruments(engine)[0].source_symbols == {}


def test_an_instruments_symbol_in_a_source_can_be_changed(engine: Engine) -> None:
    saved = add_instrument(engine, InstrumentDraft("ISAC", 3, "USD", "LSE", source_symbols={YAHOO: "ISAC.L"}))

    update_instrument(engine, saved.id, InstrumentDraft("ISAC", 3, "USD", "LSE", source_symbols={YAHOO: " SSAC.L "}))

    assert list_instruments(engine)[0].source_symbols == {YAHOO: "SSAC.L"}


def _quote(price: str, day: date) -> Quote:
    return Quote(Decimal(price), "USD", day, YAHOO)


def test_the_newest_quote_of_each_instrument_is_its_current_price(engine: Engine) -> None:
    isac = add_instrument(engine, InstrumentDraft("ISAC", 3, "USD", "LSE"))
    aapl = add_instrument(engine, InstrumentDraft("AAPL", 3, "USD", "NASDAQ"))
    save_quote(engine, isac.id, _quote("123.44", date(2026, 10, 8)), FETCHED)
    save_quote(engine, isac.id, _quote("123.91", date(2026, 10, 9)), FETCHED)
    save_quote(engine, aapl.id, _quote("254.63", date(2026, 10, 9)), FETCHED)

    assert latest_quotes(engine) == {
        isac.id: _quote("123.91", date(2026, 10, 9)),
        aapl.id: _quote("254.63", date(2026, 10, 9)),
    }


def test_a_later_fetch_on_the_same_day_replaces_that_days_quote(engine: Engine) -> None:
    isac = add_instrument(engine, InstrumentDraft("ISAC", 3, "USD", "LSE"))
    save_quote(engine, isac.id, _quote("123.50", date(2026, 10, 9)), FETCHED)
    save_quote(engine, isac.id, _quote("123.91", date(2026, 10, 9)), FETCHED)

    assert latest_quotes(engine) == {isac.id: _quote("123.91", date(2026, 10, 9))}


def test_deleting_an_instrument_removes_its_quotes(engine: Engine) -> None:
    isac = add_instrument(engine, InstrumentDraft("ISAC", 3, "USD", "LSE", source_symbols={YAHOO: "ISAC.L"}))
    save_quote(engine, isac.id, _quote("123.91", date(2026, 10, 9)), FETCHED)

    delete_instrument(engine, isac.id)
    again = add_instrument(engine, InstrumentDraft("ISAC", 3, "USD", "LSE"))

    assert latest_quotes(engine) == {}
    assert again.source_symbols == {}
