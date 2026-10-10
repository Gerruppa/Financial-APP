"""An Instrument's price for valuing its Positions, and why it has none (spec 4.1).

The Manual Price wins while it is set; otherwise the Instrument's newest Quote from the Price Sources is its price.
A badge beside the Position says where the price comes from when it is not a fresh Quote.
"""

from collections.abc import Callable
from dataclasses import dataclass
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
    """``price`` is in ``currency``, the Instrument's quote currency; ``pln`` is that price in PLN.

    ``quote`` is the newest Quote, also when the Manual Price wins, so that it can be shown beside it.
    """

    price: Decimal | None
    currency: str
    pln: Decimal | None
    status: PriceStatus
    quote: Quote | None = None
    badge: Badge | None = None


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
    rate = rate_for(currency)
    if rate is None:
        return InstrumentPrice(price, currency, None, PriceStatus.NO_RATE, quote, badge)
    return InstrumentPrice(price, currency, price * rate, status, quote, badge)


def _badge(instrument: Instrument, quote: Quote | None, stale: bool) -> Badge | None:
    if instrument.asset_class_name in STAGE_3_CLASSES:
        return Badge.STAGE_3
    if instrument.manual_price is not None:
        return Badge.MANUAL
    if not sources_to_try(instrument.asset_class_name, instrument.source_symbols):
        return Badge.NO_SOURCE
    if quote is not None and stale:
        return Badge.STALE
    return None
