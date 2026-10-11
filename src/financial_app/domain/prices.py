"""Quotes from the Price Sources and the Fallback Order they are tried in (spec 4.1, ADR-0005)."""

from collections.abc import Iterable, Mapping, Sequence
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


def source_reason(source: str, reason: str) -> str:
    """Why a Price Source gave no Quote, named as in the UI: "Yahoo: <reason>"."""
    return f"{SOURCE_NAMES.get(source, source)}: {reason}"


# The Price Sources a Fallback Order can name, in the order the UI offers them
FALLBACK_SOURCES = (YAHOO, BOSSA, ANALIZY, BANKIER)
# Spec 4.1 defaults for the seeded Asset Classes; each class keeps its own, editable order (issue #41)
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


def default_fallback_order(asset_class: str) -> tuple[str, ...]:
    """The spec 4.1 Fallback Order of a seeded Asset Class; any other class gets the order of "Inne"."""
    return DEFAULT_FALLBACK_ORDERS.get(asset_class, DEFAULT_FALLBACK_ORDERS[OTHER])


class FallbackOrderError(ValueError):
    """A Fallback Order the user must correct; the message is shown in the UI (Polish)."""


def validate_fallback_order(order: Iterable[str]) -> tuple[str, ...]:
    """The Fallback Order the user chose: known Price Sources, each at most once."""
    result: list[str] = []
    for source in order:
        name = SOURCE_NAMES.get(source, source)
        if source not in FALLBACK_SOURCES:
            raise FallbackOrderError(f"Źródło {name} nie może wyceniać instrumentów.")
        if source in result:
            raise FallbackOrderError(f"Źródło {name} jest w kolejności dwa razy.")
        result.append(source)
    return tuple(result)


def sources_to_try(fallback_order: Sequence[str], symbols: Mapping[str, str]) -> list[tuple[str, str]]:
    """The Price Sources to try for an Instrument whose Asset Class has ``fallback_order``, each with the Instrument's
    Source Symbol in it; only sources the Instrument has a Source Symbol for are tried."""
    return [(source, symbols[source]) for source in fallback_order if source in symbols]


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


class CurrencyMismatchError(PriceSourceError):
    """The source quotes the symbol in another currency than the Instrument's, which is never converted silently
    (spec 4.1); ``quote`` is the source's own, in the source's currency rather than the Instrument's quote currency, for
    the "Sprawdź" check to show and never to be saved."""

    def __init__(self, message: str, quote: Quote) -> None:
        super().__init__(message)
        self.quote = quote
