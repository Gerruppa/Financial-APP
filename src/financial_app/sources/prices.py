"""Refreshing the Quotes of held Instruments from the Price Sources, in each Fallback Order (spec 4.1)."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import Engine

from financial_app.domain.lots import open_positions
from financial_app.domain.prices import PriceSourceError, Quote, sources_to_try
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.quotes import load_refresh, save_quote, save_refresh
from financial_app.persistence.transactions import list_transactions


class PriceSource(Protocol):
    """A Price Source module, e.g. ``sources.yahoo.YahooSource``."""

    name: str

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
    ``last_refresh``.
    """
    # list_transactions is newest first; the FIFO engine wants entry order
    held = {position.instrument_id for position in open_positions(reversed(list_transactions(engine)))}
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
            save_quote(engine, instrument.id, quote, now())
            refreshed += 1
            break
        else:
            failures.append(RefreshFailure(instrument.id, instrument.name, reasons))
    save_refresh(engine, now(), {failure.instrument_id: failure.reasons for failure in failures})
    return RefreshResult(refreshed, failures)


def last_refresh(engine: Engine) -> RefreshStatus | None:
    """The last refresh with its failing Instruments in the Instrument list's order; ``None`` before the first."""
    saved = load_refresh(engine)
    if saved is None:
        return None
    refreshed_at, reasons = saved
    failures = [RefreshFailure(i.id, i.name, reasons[i.id]) for i in list_instruments(engine) if i.id in reasons]
    return RefreshStatus(refreshed_at, failures)
