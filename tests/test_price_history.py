"""An Instrument's Quotes in a date range, with the missing days fetched once from Stooq and then read from the cache
(issue #33, spec 4.1), on saved responses without the network."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.prices import BOSSA, STOOQ, PriceSourceError, Quote
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import (
    add_asset_class,
    add_instrument,
    delete_instrument,
    list_instruments,
    update_instrument,
)
from financial_app.persistence.quotes import latest_quotes, save_quote
from financial_app.persistence.reset import clear_portfolio
from financial_app.persistence.settings import STOOQ_API_KEY, save_setting
from financial_app.sources.history import QuoteHistory

FIXTURES = Path(__file__).parent / "fixtures" / "stooq"
NOW = datetime(2026, 10, 10, 9, 30)
JAN_2 = date(2026, 1, 2)
JAN_9 = date(2026, 1, 9)


class SavedStooq:
    """Answers with the saved CSV for the symbol in the URL ("Brak danych" without one) and records the URLs."""

    def __init__(self) -> None:
        self.requests: list[str] = []

    def __call__(self, url: str) -> str:
        self.requests.append(url)
        saved = FIXTURES / f"{url.split('s=', 1)[1].split('&', 1)[0]}.csv"
        return saved.read_text(encoding="utf-8") if saved.is_file() else "Brak danych"

    def ranges(self) -> list[str]:
        return [url.split("&d1=", 1)[1].split("&i=", 1)[0] for url in self.requests]


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = init_db(tmp_path / "app.sqlite3")
    save_setting(engine, STOOQ_API_KEY, "KEY")
    return engine


def _index(engine: Engine, symbol: str = "wig") -> int:
    """An index saved as an Instrument in an Asset Class of its own, with only a Stooq Source Symbol."""
    indices = add_asset_class(engine, "Indeksy")
    return add_instrument(engine, InstrumentDraft("WIG", indices.id, "PLN", "GPW", source_symbols={STOOQ: symbol})).id


def _history(engine: Engine, stooq: SavedStooq, today: date = date(2026, 10, 10)) -> QuoteHistory:
    return QuoteHistory(engine, fetch=stooq, today=lambda: today, now=lambda: NOW)


def test_an_index_saved_as_an_instrument_has_its_history_fetched(engine: Engine) -> None:
    wig = _index(engine)

    quotes = _history(engine, SavedStooq()).between(wig, JAN_2, JAN_9)

    assert [q.day.day for q in quotes] == [2, 5, 7, 8, 9]
    assert quotes[0] == Quote(Decimal("118702.33"), "PLN", JAN_2, STOOQ)


def test_days_fetched_once_are_read_from_the_cache(engine: Engine) -> None:
    wig = _index(engine)
    stooq = SavedStooq()
    first = _history(engine, stooq).between(wig, JAN_2, JAN_9)

    # A new instance, as after a restart, still finds them, the holiday (6 January) and the weekend included
    again = _history(engine, stooq).between(wig, JAN_2, JAN_9)

    assert again == first
    assert stooq.ranges() == ["20260102&d2=20260109"]


def test_only_the_missing_days_are_fetched(engine: Engine) -> None:
    wig = _index(engine)
    stooq = SavedStooq()
    _history(engine, stooq).between(wig, JAN_2, JAN_9)

    _history(engine, stooq).between(wig, date(2025, 12, 29), date(2026, 1, 20))

    assert stooq.ranges() == ["20260102&d2=20260109", "20251229&d2=20260101", "20260110&d2=20260120"]


def test_history_is_fetched_up_to_yesterday_and_today_is_left_to_the_price_refresh(engine: Engine) -> None:
    wig = _index(engine)
    stooq = SavedStooq()
    today = date(2026, 1, 9)
    save_quote(engine, wig, Quote(Decimal("120000"), "PLN", today, BOSSA), NOW)

    quotes = _history(engine, stooq, today).between(wig, JAN_2, today)
    _history(engine, stooq, today).between(wig, JAN_2, today)

    assert stooq.ranges() == ["20260102&d2=20260108"]
    # The Stooq row for the 9th is not taken: today's Quote stays the current price
    assert quotes[-1] == Quote(Decimal("120000"), "PLN", today, BOSSA)
    assert latest_quotes(engine)[wig] == quotes[-1]


def test_history_fills_only_days_without_a_quote(engine: Engine) -> None:
    wig = _index(engine)
    save_quote(engine, wig, Quote(Decimal("118000"), "PLN", JAN_2, BOSSA), NOW)

    quotes = _history(engine, SavedStooq()).between(wig, JAN_2, date(2026, 1, 5))

    assert quotes == [
        Quote(Decimal("118000"), "PLN", JAN_2, BOSSA),
        Quote(Decimal("119380.17"), "PLN", date(2026, 1, 5), STOOQ),
    ]


def test_stooq_history_never_becomes_the_current_price(engine: Engine) -> None:
    wig = _index(engine)
    save_quote(engine, wig, Quote(Decimal("117000"), "PLN", date(2025, 12, 30), BOSSA), NOW)

    _history(engine, SavedStooq()).between(wig, JAN_2, JAN_9)

    assert latest_quotes(engine)[wig] == Quote(Decimal("117000"), "PLN", date(2025, 12, 30), BOSSA)


def test_days_stooq_may_not_have_published_yet_are_asked_again(engine: Engine) -> None:
    wig = _index(engine)
    stooq = SavedStooq()
    # On Monday the 12th Stooq has nothing after Friday the 9th yet; the weekend may still be quiet, so the last
    # three days are not taken as fetched until Stooq has a Quote on or after them
    _history(engine, stooq, date(2026, 1, 12)).between(wig, JAN_2, date(2026, 1, 11))
    _history(engine, stooq, date(2026, 1, 12)).between(wig, JAN_2, date(2026, 1, 11))
    _history(engine, stooq, date(2026, 1, 12)).between(wig, JAN_2, JAN_9)

    assert stooq.ranges() == ["20260102&d2=20260111", "20260110&d2=20260111"]


def test_stooq_history_is_only_for_instruments_quoted_in_pln(engine: Engine) -> None:
    acwi = add_instrument(engine, InstrumentDraft("ACWI", 3, "USD", "LSE", source_symbols={STOOQ: "acwi.uk"})).id
    stooq = SavedStooq()

    with pytest.raises(PriceSourceError, match="tylko w PLN"):
        _history(engine, stooq).between(acwi, JAN_2, JAN_9)
    assert stooq.requests == []


def test_an_instrument_without_a_stooq_symbol_has_only_its_saved_quotes(engine: Engine) -> None:
    pzu = add_instrument(engine, InstrumentDraft("PZU", 2, "PLN", "GPW", source_symbols={BOSSA: "PZU"})).id
    save_quote(engine, pzu, Quote(Decimal("50.1"), "PLN", JAN_2, BOSSA), NOW)
    stooq = SavedStooq()

    assert _history(engine, stooq).between(pzu, JAN_2, JAN_9) == [Quote(Decimal("50.1"), "PLN", JAN_2, BOSSA)]
    assert stooq.requests == []


def test_a_failed_fetch_is_reported_and_asked_again_next_time(engine: Engine) -> None:
    wig = _index(engine)
    save_setting(engine, STOOQ_API_KEY, "")
    stooq = SavedStooq()

    with pytest.raises(PriceSourceError, match="Brak klucza API Stooq"):
        _history(engine, stooq).between(wig, JAN_2, JAN_9)
    save_setting(engine, STOOQ_API_KEY, "KEY")

    assert len(_history(engine, stooq).between(wig, JAN_2, JAN_9)) == 5


def test_a_new_stooq_symbol_drops_the_old_history(engine: Engine) -> None:
    wig = _index(engine, symbol="wig20")
    stooq = SavedStooq()
    assert _history(engine, stooq).between(wig, JAN_2, JAN_9) == []

    indices = list_instruments(engine)[0].asset_class_id
    update_instrument(engine, wig, InstrumentDraft("WIG", indices, "PLN", "GPW", source_symbols={STOOQ: "wig"}))

    assert len(_history(engine, stooq).between(wig, JAN_2, JAN_9)) == 5


def test_a_stooq_symbol_changed_only_in_case_keeps_the_history(engine: Engine) -> None:
    wig = _index(engine)
    stooq = SavedStooq()
    _history(engine, stooq).between(wig, JAN_2, JAN_9)
    indices = list_instruments(engine)[0].asset_class_id

    update_instrument(engine, wig, InstrumentDraft("WIG", indices, "PLN", "GPW", source_symbols={STOOQ: "WIG"}))

    assert len(_history(engine, stooq).between(wig, JAN_2, JAN_9)) == 5
    assert len(stooq.requests) == 1


def test_a_deleted_instrument_takes_its_history_along(engine: Engine) -> None:
    wig = _index(engine)
    stooq = SavedStooq()
    _history(engine, stooq).between(wig, JAN_2, JAN_9)
    indices = list_instruments(engine)[0].asset_class_id

    delete_instrument(engine, wig)
    # SQLite gives the next Instrument the freed id, which must not find the old history
    again = add_instrument(engine, InstrumentDraft("WIG", indices, "PLN", "GPW", source_symbols={STOOQ: "wig"})).id

    assert again == wig
    assert len(_history(engine, stooq).between(again, JAN_2, JAN_9)) == 5
    assert len(stooq.requests) == 2


def test_clearing_the_portfolio_removes_the_history_too(engine: Engine) -> None:
    wig = _index(engine)
    stooq = SavedStooq()
    _history(engine, stooq).between(wig, JAN_2, JAN_9)

    clear_portfolio(engine)
    again = _index(engine)

    assert again == wig
    assert len(_history(engine, stooq).between(again, JAN_2, JAN_9)) == 5
    assert len(stooq.requests) == 2
