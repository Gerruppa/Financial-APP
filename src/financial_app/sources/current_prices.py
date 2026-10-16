"""Today's valuation inputs shared by the Portfolio and the Dashboard: each Instrument's price from
``domain.valuation`` (a Bond Series' from its saved MF rates and GUS CPI) and the NBP Rates from the last business day
before today, each currency fetched once."""

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine

from financial_app.domain.currencies import MissingNbpRateError
from financial_app.domain.instruments import Instrument
from financial_app.domain.transactions import PLN
from financial_app.domain.valuation import InstrumentPrice, instrument_price
from financial_app.persistence.bond_series import load_bond_data
from financial_app.persistence.quotes import latest_quotes
from financial_app.sources.nbp import NbpRates
from financial_app.sources.prices import RefreshStatus


class TodaysRates:
    """The NBP Rate of each currency asked for, ``None`` when NBP has none; PLN is 1."""

    def __init__(self, rates: NbpRates) -> None:
        self.rates = rates
        self.asked: dict[str, Decimal | None] = {PLN: Decimal(1)}

    def today(self) -> date:
        """The day the rates are today's for."""
        return self.rates.today()

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
    """Each Instrument's price by id, its newest Quote marked stale when the last ``refresh`` failed for it; a Bond
    Series is valued at the end of the NBP Rates' today."""
    quotes = latest_quotes(engine)
    stale = {failure.instrument_id for failure in refresh.failures} if refresh else set()
    bonds = load_bond_data(engine)
    today = rates.today()
    return {
        i.id: instrument_price(i, quotes.get(i.id), rates, i.id in stale, bonds.price(i.id, today)) for i in instruments
    }
