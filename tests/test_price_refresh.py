"""Refreshing the Quotes of held Instruments from the Price Sources (issue #30, spec 4.1), with fake sources."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import Instrument, InstrumentDraft
from financial_app.domain.prices import BOSSA, YAHOO, PriceSourceError, Quote
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, delete_instrument
from financial_app.persistence.quotes import latest_quotes
from financial_app.persistence.transactions import add_transaction, delete_transaction
from financial_app.sources.prices import (
    PriceSource,
    RefreshFailure,
    RefreshResult,
    RefreshStatus,
    last_refresh,
    refresh_prices,
)

NOW = datetime(2026, 10, 9, 18, 5)
FRIDAY = date(2026, 10, 9)
AKCJE_POLSKIE = 2


class FakeSource:
    """A Price Source answering from ``prices`` by symbol; any other symbol fails."""

    def __init__(self, name: str, prices: dict[str, str]) -> None:
        self.name = name
        self.prices = prices
        self.asked: list[str] = []

    def quote(self, symbol: str, currency: str) -> Quote:
        self.asked.append(symbol)
        if symbol not in self.prices:
            raise PriceSourceError(f"{self.name} nie zna symbolu „{symbol}”.")
        return Quote(Decimal(self.prices[symbol]), currency, FRIDAY, self.name)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _held(engine: Engine, name: str, symbols: dict[str, str]) -> Instrument:
    """An Instrument bought on an Account, so that it has an open Position."""
    account = add_account(engine, AccountDraft(f"Konto {name}", "XTB", AccountType.REGULAR, ("PLN",)))
    instrument = add_instrument(engine, InstrumentDraft(name, AKCJE_POLSKIE, "PLN", source_symbols=symbols))
    add_transaction(engine, TransactionDraft(account.id, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(1000)))
    add_transaction(
        engine, buy_or_sell(account.id, date(2026, 1, 5), TransactionType.BUY, instrument.id, Decimal(10), Decimal(40))
    )
    return instrument


def test_a_held_instrument_gets_its_newest_quote(engine: Engine) -> None:
    pzu = _held(engine, "PZU", {YAHOO: "PZU.WA"})

    refresh_prices(engine, {YAHOO: FakeSource(YAHOO, {"PZU.WA": "45.12"})}, lambda: NOW)

    assert latest_quotes(engine) == {pzu.id: Quote(Decimal("45.12"), "PLN", FRIDAY, YAHOO)}


def test_an_instrument_without_an_open_position_is_not_fetched(engine: Engine) -> None:
    add_instrument(engine, InstrumentDraft("CDR", AKCJE_POLSKIE, "PLN", source_symbols={YAHOO: "CDR.WA"}))
    yahoo = FakeSource(YAHOO, {"CDR.WA": "250"})

    refresh_prices(engine, {YAHOO: yahoo}, lambda: NOW)

    assert yahoo.asked == []
    assert latest_quotes(engine) == {}


def test_when_the_first_source_fails_the_next_one_in_the_order_is_tried(engine: Engine) -> None:
    # Akcje polskie: Bossa, then Yahoo
    pzu = _held(engine, "PZU", {BOSSA: "PZU", YAHOO: "PZU.WA"})
    sources = {BOSSA: FakeSource(BOSSA, {}), YAHOO: FakeSource(YAHOO, {"PZU.WA": "45.12"})}

    result = refresh_prices(engine, sources, lambda: NOW)

    assert latest_quotes(engine) == {pzu.id: Quote(Decimal("45.12"), "PLN", FRIDAY, YAHOO)}
    assert result == RefreshResult(refreshed=1, failures=[])


def test_an_instrument_failing_in_every_source_is_reported_and_the_others_still_refresh(engine: Engine) -> None:
    aaa = _held(engine, "AAA", {BOSSA: "AAA", YAHOO: "AAA.WA"})
    pzu = _held(engine, "PZU", {YAHOO: "PZU.WA"})
    sources = {BOSSA: FakeSource(BOSSA, {}), YAHOO: FakeSource(YAHOO, {"PZU.WA": "45.12"})}

    result = refresh_prices(engine, sources, lambda: NOW)

    assert list(latest_quotes(engine)) == [pzu.id]
    assert result == RefreshResult(
        refreshed=1,
        failures=[
            RefreshFailure(
                aaa.id, "AAA", {BOSSA: "bossa nie zna symbolu „AAA”.", YAHOO: "yahoo nie zna symbolu „AAA.WA”."}
            )
        ],
    )


def test_a_symbol_in_a_source_the_app_does_not_have_yet_is_skipped(engine: Engine) -> None:
    _held(engine, "PZU", {BOSSA: "PZU"})

    result = refresh_prices(engine, {YAHOO: FakeSource(YAHOO, {})}, lambda: NOW)

    assert result == RefreshResult(refreshed=0, failures=[])


def test_before_any_refresh_there_is_no_status(engine: Engine) -> None:
    assert last_refresh(engine) is None


def test_the_last_refresh_is_kept_with_its_time_and_the_instruments_that_failed(engine: Engine) -> None:
    aaa = _held(engine, "AAA", {YAHOO: "AAA.WA"})
    _held(engine, "PZU", {YAHOO: "PZU.WA"})

    refresh_prices(engine, {YAHOO: FakeSource(YAHOO, {"PZU.WA": "45.12"})}, lambda: NOW)

    assert last_refresh(engine) == RefreshStatus(
        NOW, [RefreshFailure(aaa.id, "AAA", {YAHOO: "yahoo nie zna symbolu „AAA.WA”."})]
    )


def test_a_successful_attempt_after_a_failure_clears_it(engine: Engine) -> None:
    _held(engine, "PZU", {YAHOO: "PZU.WA"})
    refresh_prices(engine, {YAHOO: FakeSource(YAHOO, {})}, lambda: NOW)

    later = datetime(2026, 10, 10, 9, 0)
    refresh_prices(engine, {YAHOO: FakeSource(YAHOO, {"PZU.WA": "45.12"})}, lambda: later)

    assert last_refresh(engine) == RefreshStatus(later, [])


def test_deleting_an_instrument_removes_its_failure(engine: Engine) -> None:
    cdr = add_instrument(engine, InstrumentDraft("CDR", AKCJE_POLSKIE, "PLN", source_symbols={YAHOO: "CDR.WA"}))
    account = add_account(engine, AccountDraft("Konto", "XTB", AccountType.REGULAR, ("PLN",)))
    add_transaction(engine, TransactionDraft(account.id, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(1000)))
    buy = add_transaction(
        engine, buy_or_sell(account.id, date(2026, 1, 5), TransactionType.BUY, cdr.id, Decimal(1), Decimal(250))
    )
    refresh_prices(engine, {YAHOO: FakeSource(YAHOO, {})}, lambda: NOW)

    delete_transaction(engine, buy.id)
    delete_instrument(engine, cdr.id)

    assert last_refresh(engine) == RefreshStatus(NOW, [])


class BrokenSource:
    """A Price Source failing in a way it does not wrap in ``PriceSourceError``."""

    name = BOSSA

    def quote(self, symbol: str, currency: str) -> Quote:
        raise ValueError("bad payload")


def test_an_unexpected_error_in_a_source_is_a_failure_and_the_next_source_is_tried(engine: Engine) -> None:
    aaa = _held(engine, "AAA", {BOSSA: "AAA"})
    pzu = _held(engine, "PZU", {BOSSA: "PZU", YAHOO: "PZU.WA"})
    sources: dict[str, PriceSource] = {BOSSA: BrokenSource(), YAHOO: FakeSource(YAHOO, {"PZU.WA": "45.12"})}

    result = refresh_prices(engine, sources, lambda: NOW)

    assert list(latest_quotes(engine)) == [pzu.id]
    assert result.failures == [RefreshFailure(aaa.id, "AAA", {BOSSA: "Nieoczekiwany błąd źródła: bad payload"})]
