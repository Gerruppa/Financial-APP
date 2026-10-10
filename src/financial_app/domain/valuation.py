"""An Instrument's price for valuing its Positions, and why it has none (spec 4.1).

Stage 1 knows only the Manual Price; Stage 2 adds Quotes from the Price Sources.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from financial_app.domain.instruments import Instrument


class PriceStatus(StrEnum):
    MANUAL = "manual"  # the Manual Price
    NO_PRICE = "no_price"  # nothing to value the Instrument at
    NO_RATE = "no_rate"  # a price in a foreign currency, but no NBP Rate to convert it


@dataclass(frozen=True)
class InstrumentPrice:
    """``price`` is in ``currency``, the Instrument's quote currency; ``pln`` is that price in PLN."""

    price: Decimal | None
    currency: str
    pln: Decimal | None
    status: PriceStatus


def instrument_price(instrument: Instrument, rate_for: Callable[[str], Decimal | None]) -> InstrumentPrice:
    """The Instrument's price, converted to PLN at ``rate_for(currency)`` (PLN for one unit of the currency)."""
    price, currency = instrument.manual_price, instrument.quote_currency
    if price is None:
        return InstrumentPrice(None, currency, None, PriceStatus.NO_PRICE)
    rate = rate_for(currency)
    if rate is None:
        return InstrumentPrice(price, currency, None, PriceStatus.NO_RATE)
    return InstrumentPrice(price, currency, price * rate, PriceStatus.MANUAL)
