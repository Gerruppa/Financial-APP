"""An Instrument's price for valuing its Positions, and why it has none (spec 4.1).

The Manual Price wins while it is set; otherwise the Instrument's newest Quote from the Price Sources is its price.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from financial_app.domain.instruments import Instrument
from financial_app.domain.prices import Quote


class PriceStatus(StrEnum):
    MANUAL = "manual"  # the Manual Price
    QUOTE = "quote"  # the newest Quote
    NO_PRICE = "no_price"  # nothing to value the Instrument at
    NO_RATE = "no_rate"  # a price in a foreign currency, but no NBP Rate to convert it


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


def instrument_price(
    instrument: Instrument, quote: Quote | None, rate_for: Callable[[str], Decimal | None]
) -> InstrumentPrice:
    """The Instrument's price, converted to PLN at ``rate_for(currency)`` (PLN for one unit of the currency).

    ``quote`` is the Instrument's newest Quote, if it has one.
    """
    currency = instrument.quote_currency
    if instrument.manual_price is not None:
        price, status = instrument.manual_price, PriceStatus.MANUAL
    elif quote is not None:
        price, status = quote.price, PriceStatus.QUOTE
    else:
        return InstrumentPrice(None, currency, None, PriceStatus.NO_PRICE)
    rate = rate_for(currency)
    if rate is None:
        return InstrumentPrice(price, currency, None, PriceStatus.NO_RATE, quote)
    return InstrumentPrice(price, currency, price * rate, status, quote)
