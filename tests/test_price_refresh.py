"""Refreshing the Quotes of held Instruments from the Price Sources (issue #30, spec 4.1), with fake sources."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import Instrument, InstrumentDraft
from financial_app.domain.prices import ANALIZY, BANKIER, BOSSA, YAHOO, PriceSourceError, Quote
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, delete_instrument, set_fallback_order
from financial_app.persistence.quotes import last_successful_refresh, latest_quotes
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
        self.refreshes = 0

    def new_refresh(self) -> None:
        self.refreshes += 1

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


def test_a_changed_fallback_order_is_followed_at_the_next_refresh(engine: Engine) -> None:
    pzu = _held(engine, "PZU", {BOSSA: "PZU", YAHOO: "PZU.WA"})
    set_fallback_order(engine, AKCJE_POLSKIE, [YAHOO])
    bossa = FakeSource(BOSSA, {"PZU": "45.10"})

    refresh_prices(engine, {BOSSA: bossa, YAHOO: FakeSource(YAHOO, {"PZU.WA": "45.12"})}, lambda: NOW)

    assert bossa.asked == []
    assert latest_quotes(engine) == {pzu.id: Quote(Decimal("45.12"), "PLN", FRIDAY, YAHOO)}


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

    def new_refresh(self) -> None:
        pass

    def quote(self, symbol: str, currency: str) -> Quote:
        raise ValueError("bad payload")


def test_an_unexpected_error_in_a_source_is_a_failure_and_the_next_source_is_tried(engine: Engine) -> None:
    aaa = _held(engine, "AAA", {BOSSA: "AAA"})
    pzu = _held(engine, "PZU", {BOSSA: "PZU", YAHOO: "PZU.WA"})
    sources: dict[str, PriceSource] = {BOSSA: BrokenSource(), YAHOO: FakeSource(YAHOO, {"PZU.WA": "45.12"})}

    result = refresh_prices(engine, sources, lambda: NOW)

    assert list(latest_quotes(engine)) == [pzu.id]
    assert result.failures == [RefreshFailure(aaa.id, "AAA", {BOSSA: "Nieoczekiwany błąd źródła: bad payload"})]


def test_each_refresh_tells_the_sources_it_starts_so_they_fetch_anew(engine: Engine) -> None:
    yahoo = FakeSource(YAHOO, {})

    refresh_prices(engine, {YAHOO: yahoo}, lambda: NOW)
    refresh_prices(engine, {YAHOO: yahoo}, lambda: NOW)

    assert yahoo.refreshes == 2


def test_a_refresh_giving_at_least_one_quote_is_the_last_success(engine: Engine) -> None:
    _held(engine, "AAA", {YAHOO: "AAA.WA"})
    _held(engine, "PZU", {YAHOO: "PZU.WA"})

    refresh_prices(engine, {YAHOO: FakeSource(YAHOO, {"PZU.WA": "45.12"})}, lambda: NOW)

    assert last_successful_refresh(engine) == NOW


def test_a_refresh_where_every_instrument_failed_is_no_success(engine: Engine) -> None:
    # e.g. no network: the next start tries again
    _held(engine, "PZU", {YAHOO: "PZU.WA"})
    refresh_prices(engine, {YAHOO: FakeSource(YAHOO, {"PZU.WA": "45.12"})}, lambda: NOW)

    refresh_prices(engine, {YAHOO: FakeSource(YAHOO, {})}, lambda: datetime(2026, 10, 12, 18, 0))

    assert last_successful_refresh(engine) == NOW


def test_a_refresh_with_nothing_to_fetch_is_a_success(engine: Engine) -> None:
    assert last_successful_refresh(engine) is None

    refresh_prices(engine, {YAHOO: FakeSource(YAHOO, {})}, lambda: NOW)

    assert last_successful_refresh(engine) == NOW


def test_bankier_gets_the_fund_code_when_analizy_fails(engine: Engine) -> None:
    fund = _held(engine, "PZU PPK 2060", {ANALIZY: "PZU60"})
    set_fallback_order(engine, AKCJE_POLSKIE, [ANALIZY, BANKIER])
    bankier = FakeSource(BANKIER, {"PZU60": "15.31"})

    refresh_prices(engine, {ANALIZY: FakeSource(ANALIZY, {}), BANKIER: bankier}, lambda: NOW)

    assert bankier.asked == ["PZU60"]
    assert latest_quotes(engine) == {fund.id: Quote(Decimal("15.31"), "PLN", FRIDAY, BANKIER)}


def test_a_bankier_symbol_of_its_own_wins_over_the_fund_code(engine: Engine) -> None:
    _held(engine, "PCS", {ANALIZY: "PCS08", BANKIER: "PCS08A2"})
    set_fallback_order(engine, AKCJE_POLSKIE, [ANALIZY, BANKIER])
    bankier = FakeSource(BANKIER, {"PCS08A2": "120"})

    refresh_prices(engine, {ANALIZY: FakeSource(ANALIZY, {}), BANKIER: bankier}, lambda: NOW)

    assert bankier.asked == ["PCS08A2"]
