"""Refreshing the Quotes of held Instruments from the Price Sources, in each Fallback Order (spec 4.1)."""

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import Engine

from financial_app.domain.lots import open_positions
from financial_app.domain.prices import CurrencyMismatchError, PriceSourceError, Quote, sources_to_try
from financial_app.domain.valuation import Unpriced, instruments_without_price
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.quotes import latest_quotes, load_refresh, save_quote, save_refresh
from financial_app.persistence.transactions import list_transactions


class PriceSource(Protocol):
    """A Price Source module, e.g. ``sources.yahoo.YahooSource``."""

    name: str

    def new_refresh(self) -> None:
        """A refresh starts: forget anything kept from an earlier one, so that Quotes are fetched anew."""
        ...

    def quote(self, symbol: str, currency: str) -> Quote:
        """The newest Quote of ``symbol`` in ``currency``; raises ``PriceSourceError`` when it has none."""
        ...


@dataclass(frozen=True)
class RefreshFailure:
    """An Instrument no source gave a Quote for, with each source's reason (Polish) by source key, in the order the
    sources were tried."""

    instrument_id: int
    instrument: str
    reasons: dict[str, str]


@dataclass(frozen=True)
class RefreshResult:
    """How many Instruments got a Quote, and the ones that failed in every source."""

    refreshed: int
    failures: list[RefreshFailure]

    @property
    def succeeded(self) -> bool:
        """Not every Instrument fetched failed (as with no network), so the next start-up need not refresh."""
        return self.refreshed > 0 or not self.failures


@dataclass(frozen=True)
class RefreshStatus:
    """The last refresh, for the header: when it ran and the Instruments that failed in it (their Prices are Stale)."""

    refreshed_at: datetime
    failures: list[RefreshFailure]


def refresh_prices(
    engine: Engine, sources: Mapping[str, PriceSource], now: Callable[[], datetime] = datetime.now
) -> RefreshResult:
    """Fetch and save a Quote for every Instrument with an open Position, from the first source that gives one.

    A failing source or Instrument never stops the others. The refresh's time and failures are saved for
    ``last_refresh``, and as the last successful one when the result ``succeeded``.
    """
    for price_source in sources.values():
        price_source.new_refresh()
    held = _held(engine)
    refreshed, failures = 0, []
    for instrument in list_instruments(engine):
        if instrument.id not in held:
            continue
        to_try = [
            (source, symbol)
            for source, symbol in sources_to_try(instrument.asset_class_name, instrument.source_symbols)
            if source in sources
        ]
        if not to_try:
            continue
        reasons = {}
        for source, symbol in to_try:
            try:
                quote = sources[source].quote(symbol, instrument.quote_currency)
            except PriceSourceError as error:
                reasons[source] = str(error)
                continue
            except Exception as error:  # noqa: BLE001 - a broken source must not stop the other Instruments
                reasons[source] = _unexpected(error)
                continue
            save_quote(engine, instrument.id, quote, now())
            refreshed += 1
            break
        else:
            failures.append(RefreshFailure(instrument.id, instrument.name, reasons))
    result = RefreshResult(refreshed, failures)
    save_refresh(engine, now(), {failure.instrument_id: failure.reasons for failure in failures}, result.succeeded)
    return result


@dataclass(frozen=True)
class SymbolCheck:
    """What the "Sprawdź" button found for one Source Symbol: the source's Quote, with a ``warning`` when it is in
    another currency than the Instrument's, or an ``error`` (Polish) when there is none."""

    quote: Quote | None = None
    warning: str = ""
    error: str = ""


def check_symbol(source: PriceSource, symbol: str, currency: str) -> SymbolCheck:
    """Fetch one Quote of ``symbol`` for an Instrument quoted in ``currency`` (spec 4.1), anew rather than from what
    the source kept from a refresh. Nothing is saved, so a failed check never stops the Instrument's save."""
    symbol, currency = symbol.strip(), currency.strip().upper()
    if not symbol:
        return SymbolCheck(error="Wpisz symbol, aby go sprawdzić.")
    if not currency:
        return SymbolCheck(error="Wpisz walutę notowania, aby sprawdzić symbol.")
    # A copy forgets what it keeps without touching the source a running refresh may be using (in another thread)
    source = copy.copy(source)
    source.new_refresh()
    try:
        return SymbolCheck(quote=source.quote(symbol, currency))
    except CurrencyMismatchError as mismatch:
        return SymbolCheck(quote=mismatch.quote, warning=str(mismatch))
    except PriceSourceError as error:
        return SymbolCheck(error=str(error))
    except Exception as error:  # noqa: BLE001 - a broken source is shown like any other failure
        return SymbolCheck(error=_unexpected(error))


def _unexpected(error: Exception) -> str:
    return f"Nieoczekiwany błąd źródła: {error}"


def last_refresh(engine: Engine) -> RefreshStatus | None:
    """The last refresh with its failing Instruments in the Instrument list's order; ``None`` before the first."""
    saved = load_refresh(engine)
    if saved is None:
        return None
    refreshed_at, reasons = saved
    failures = [RefreshFailure(i.id, i.name, reasons[i.id]) for i in list_instruments(engine) if i.id in reasons]
    return RefreshStatus(refreshed_at, failures)


def unpriced_instruments(engine: Engine) -> list[Unpriced]:
    """The "Instrumenty bez wyceny" list (issue #40): held Instruments without an automatic price after the last
    refresh, in the Instrument list's order."""
    saved = load_refresh(engine)
    failures = saved[1] if saved else {}
    return instruments_without_price(list_instruments(engine), _held(engine), latest_quotes(engine).keys(), failures)


def _held(engine: Engine) -> set[int]:
    """The ids of the Instruments with an open Position."""
    # list_transactions is newest first; the FIFO engine wants entry order
    return {position.instrument_id for position in open_positions(reversed(list_transactions(engine)))}
