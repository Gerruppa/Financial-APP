"""Today's valuation inputs shared by the Portfolio and the Dashboard: each Instrument's price from
``domain.valuation`` and the NBP Rates from the last business day before today, each currency fetched once."""

from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import Engine

from financial_app.domain.currencies import MissingNbpRateError
from financial_app.domain.instruments import Instrument
from financial_app.domain.transactions import PLN
from financial_app.domain.valuation import InstrumentPrice, instrument_price
from financial_app.persistence.quotes import latest_quotes
from financial_app.sources.nbp import NbpRates
from financial_app.sources.prices import RefreshStatus


class TodaysRates:
    """The NBP Rate of each currency asked for, ``None`` when NBP has none; PLN is 1."""

    def __init__(self, rates: NbpRates) -> None:
        self.rates = rates
        self.asked: dict[str, Decimal | None] = {PLN: Decimal(1)}

    def __call__(self, currency: str) -> Decimal | None:
        if currency not in self.asked:
            try:
                self.asked[currency] = self.rates.latest(currency).rate
            except MissingNbpRateError:
                self.asked[currency] = None
        return self.asked[currency]

    def known(self) -> dict[str, Decimal]:
        """The rates found so far, by currency."""
        return {currency: rate for currency, rate in self.asked.items() if rate is not None}


def current_prices(
    engine: Engine, instruments: Iterable[Instrument], rates: TodaysRates, refresh: RefreshStatus | None
) -> dict[int, InstrumentPrice]:
    """Each Instrument's price by id, its newest Quote marked stale when the last ``refresh`` failed for it."""
    quotes = latest_quotes(engine)
    stale = {failure.instrument_id for failure in refresh.failures} if refresh else set()
    return {i.id: instrument_price(i, quotes.get(i.id), rates, i.id in stale) for i in instruments}
