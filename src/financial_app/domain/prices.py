"""Quotes from the Price Sources and the Fallback Order they are tried in (spec 4.1, ADR-0005)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

# Price Sources by the key their Source Symbols are saved under
YAHOO = "yahoo"
BOSSA = "bossa"
ANALIZY = "analizy"
BANKIER = "bankier"
# Stooq serves price history and indices only (issue #33), so it is in no Fallback Order
STOOQ = "stooq"
# How each Price Source is named in the UI
SOURCE_NAMES = {YAHOO: "Yahoo", BOSSA: "Bossa", ANALIZY: "analizy.pl", BANKIER: "bankier.pl", STOOQ: "Stooq"}

# Spec 4.1 defaults for the seeded Asset Classes; until they become editable (issue #41) they follow the class name
OTHER = "Inne"
DEFAULT_FALLBACK_ORDERS: dict[str, tuple[str, ...]] = {
    "Gotówka": (),
    "Akcje polskie": (BOSSA, YAHOO),
    "Akcje zagraniczne": (YAHOO, BOSSA),
    # Valued from the MF data in Stage 3
    "Obligacje skarbowe polskie": (),
    "Obligacje skarbowe zagraniczne": (YAHOO,),
    "Obligacje korporacyjne polskie": (BOSSA,),
    "Obligacje korporacyjne zagraniczne": (YAHOO,),
    "Metale i surowce": (YAHOO,),
    "Kryptowaluty": (YAHOO,),
    "Waluty": (),
    OTHER: (ANALIZY, BANKIER, YAHOO, BOSSA),
    "Multi-asset": (ANALIZY, BANKIER, YAHOO, BOSSA),
}
# Asset Classes of the Bond Series, which keep their Manual Price until Stage 3 values them from the MF data
STAGE_3_CLASSES = frozenset({"Obligacje skarbowe polskie"})


def sources_to_try(asset_class: str, symbols: Mapping[str, str]) -> list[tuple[str, str]]:
    """The Price Sources to try for an Instrument of ``asset_class``, each with the Instrument's Source Symbol in it.

    Only sources the Instrument has a Source Symbol for are tried, in its Asset Class's Fallback Order; a class the
    user added has the order of "Inne".
    """
    order = DEFAULT_FALLBACK_ORDERS.get(asset_class, DEFAULT_FALLBACK_ORDERS[OTHER])
    return [(source, symbols[source]) for source in order if source in symbols]


# When the day's prices are final enough for the start-up refresh: after the GPW session with its closing auction (local
# time). There is no exchange holiday calendar; a holiday only costs a refresh that brings the same Quotes.
SESSION_CLOSE = time(17, 30)


def last_weekday_close(now: datetime) -> datetime:
    """The most recent ``SESSION_CLOSE`` on a weekday, at or before ``now``."""
    close = datetime.combine(now.date(), SESSION_CLOSE)
    if close > now:
        close -= timedelta(days=1)
    while close.weekday() >= 5:  # Saturday, Sunday
        close -= timedelta(days=1)
    return close


def refresh_due(last_success: datetime | None, now: datetime) -> bool:
    """Whether the prices are refreshed at start-up: the last successful refresh (``None`` before the first) was before
    the most recent weekday close (spec 4.1)."""
    return last_success is None or last_success < last_weekday_close(now)


class PriceSourceError(Exception):
    """A Price Source gave no Quote for a symbol; the message says why, in Polish, for the refresh status."""


@dataclass(frozen=True)
class Quote:
    """The price of an Instrument on ``day`` in ``currency`` (its quote currency), as given by ``source``."""

    price: Decimal
    currency: str
    day: date
    source: str
