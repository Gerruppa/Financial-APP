"""An Instrument's price for valuing its Positions, and why it has none (spec 4.1).

The Manual Price wins while it is set; otherwise the Instrument's newest Quote from the Price Sources is its price.
A badge beside the Position says where the price comes from when it is not a fresh Quote. A physical metal's price is
the spot of a troy ounce, so its unit is valued at its weight less the Buyback Spread, with the spot kept beside it.
The "Instrumenty bez wyceny" list leads the user through the held Instruments without an automatic price.
"""

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from financial_app.domain.instruments import Instrument
from financial_app.domain.prices import STAGE_3_CLASSES, Quote, sources_to_try


class PriceStatus(StrEnum):
    MANUAL = "manual"  # the Manual Price
    QUOTE = "quote"  # the newest Quote
    NO_PRICE = "no_price"  # nothing to value the Instrument at
    NO_RATE = "no_rate"  # a price in a foreign currency, but no NBP Rate to convert it


class Badge(StrEnum):
    """Shown beside a Position, in Polish (spec 4.1)."""

    MANUAL = "ręczna"  # valued at the Manual Price
    STALE = "nieaktualna"  # the Quote's latest refresh failed in every Price Source
    NO_SOURCE = "bez źródła"  # no Source Symbol for any source of its Fallback Order
    STAGE_3 = "do etapu 3"  # a Bond Series, valued from the MF data in Stage 3


@dataclass(frozen=True)
class InstrumentPrice:
    """``price`` is one unit's price in ``currency``, the Instrument's quote currency; ``pln`` is that price in PLN.

    ``quote`` is the newest Quote, also when the Manual Price wins, so that it can be shown beside it. For a physical
    metal, ``spot`` is the spot of a troy ounce (in ``currency``) that ``price`` comes from and ``unit_spot_pln`` one
    unit at the spot without the Buyback Spread, in PLN; both are ``None`` for any other Instrument.
    """

    price: Decimal | None
    currency: str
    pln: Decimal | None
    status: PriceStatus
    quote: Quote | None = None
    badge: Badge | None = None
    spot: Decimal | None = None
    unit_spot_pln: Decimal | None = None


def instrument_price(
    instrument: Instrument, quote: Quote | None, rate_for: Callable[[str], Decimal | None], stale: bool = False
) -> InstrumentPrice:
    """The Instrument's price, converted to PLN at ``rate_for(currency)`` (PLN for one unit of the currency).

    ``quote`` is the Instrument's newest Quote, if it has one; ``stale`` says the latest refresh failed for it in
    every Price Source, so the Quote still values it, marked as stale.
    """
    currency = instrument.quote_currency
    badge = _badge(instrument, quote, stale)
    if instrument.manual_price is not None:
        price, status = instrument.manual_price, PriceStatus.MANUAL
    elif quote is not None:
        price, status = quote.price, PriceStatus.QUOTE
    else:
        return InstrumentPrice(None, currency, None, PriceStatus.NO_PRICE, badge=badge)
    unit = instrument.unit_price(price)
    metal = instrument.metal_grams is not None
    spot = price if metal else None
    rate = rate_for(currency)
    if rate is None:
        return InstrumentPrice(unit, currency, None, PriceStatus.NO_RATE, quote, badge, spot)
    unit_spot_pln = instrument.unit_spot(price) * rate if metal else None
    return InstrumentPrice(unit, currency, unit * rate, status, quote, badge, spot, unit_spot_pln)


def _badge(instrument: Instrument, quote: Quote | None, stale: bool) -> Badge | None:
    if instrument.asset_class_name in STAGE_3_CLASSES:
        return Badge.STAGE_3
    if instrument.manual_price is not None:
        return Badge.MANUAL
    if not sources_to_try(instrument.fallback_order, instrument.source_symbols):
        return Badge.NO_SOURCE
    if quote is not None and stale:
        return Badge.STALE
    return None


class UnpricedReason(StrEnum):
    """Why a held Instrument has no automatic price, in Polish (issue #40)."""

    NO_SOURCE = "bez źródła"  # no Source Symbol for any source of its Fallback Order
    FAILED = "błąd we wszystkich źródłach"  # the latest refresh failed in every source it has a Source Symbol for
    NOT_REFRESHED = "czeka na odświeżenie wycen"  # it has a Source Symbol but no Quote yet


@dataclass(frozen=True)
class Unpriced:
    """A row of the "Instrumenty bez wyceny" list; ``failures`` are each source's reason when the refresh failed."""

    instrument: Instrument
    reason: UnpricedReason
    failures: dict[str, str] = field(default_factory=dict)


def instruments_without_price(
    instruments: Iterable[Instrument],
    held: Collection[int],
    quoted: Collection[int],
    failures: Mapping[int, Mapping[str, str]],
) -> list[Unpriced]:
    """The ``held`` Instruments (ids with an open Position) without an automatic price, in the order given.

    ``quoted`` are the ids of the Instruments with a Quote and ``failures`` the latest refresh's reasons by Instrument
    id. A Bond Series waits for Stage 3, so it is never listed.
    """
    listed = []
    for instrument in instruments:
        if instrument.id not in held or instrument.asset_class_name in STAGE_3_CLASSES:
            continue
        if not sources_to_try(instrument.fallback_order, instrument.source_symbols):
            listed.append(Unpriced(instrument, UnpricedReason.NO_SOURCE))
        elif instrument.id in failures:
            listed.append(Unpriced(instrument, UnpricedReason.FAILED, dict(failures[instrument.id])))
        elif instrument.id not in quoted:
            listed.append(Unpriced(instrument, UnpricedReason.NOT_REFRESHED))
    return listed
