"""History of the whole Portfolio (spec 6.1, ADR-0002): the daily prices and NBP Rates it needs fetched into the
local cache, then each day's value computed from the cache alone and kept in memory until the data changes."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date

from nicegui import run
from sqlalchemy import Engine

from financial_app.domain.bond_valuation import BondData
from financial_app.domain.currencies import MissingNbpRateError, NbpRate
from financial_app.domain.history import ONE_DAY
from financial_app.domain.instruments import Instrument
from financial_app.domain.portfolio_history import DayValue, HistoryPrice, daily_history
from financial_app.domain.prices import PriceSourceError
from financial_app.domain.term_deposits import Accruals, tax_rates_of
from financial_app.domain.transactions import PLN, Transaction
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.benchmarks import list_benchmarks
from financial_app.persistence.bond_series import load_bond_data
from financial_app.persistence.history import history_prices, nbp_rates_between
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.term_deposits import list_deposits
from financial_app.persistence.transactions import list_transactions, transactions_in_entry_order
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates

type Compute = Callable[..., Awaitable[list[DayValue]]]


@dataclass(frozen=True)
class HistoryInputs:
    """Everything ``daily_history`` needs, read from the database."""

    transactions: list[Transaction]
    instruments: dict[int, Instrument]
    prices: dict[int, list[HistoryPrice]]
    rates: dict[str, list[NbpRate]]
    first: date
    last: date
    bonds: BondData = field(default_factory=BondData)
    accruals: Accruals | None = None


@dataclass(frozen=True)
class HistoryFetch:
    """What a fetch could not get: the reason by Instrument id and by currency."""

    instruments: dict[int, str] = field(default_factory=dict)
    currencies: dict[str, str] = field(default_factory=dict)


def history_inputs(engine: Engine, today: date) -> HistoryInputs | None:
    """What History is computed from up to ``today``, read from the cache alone; ``None`` without any Transaction."""
    transactions = transactions_in_entry_order(engine)
    if not transactions:
        return None
    instruments = {instrument.id: instrument for instrument in list_instruments(engine)}
    first = min(t.date for t in transactions)
    currencies = {t.cash_currency for t in transactions} | {i.quote_currency for i in instruments.values()}
    return HistoryInputs(
        transactions,
        instruments,
        {instrument_id: history_prices(engine, instrument_id) for instrument_id in instruments},
        {
            currency: nbp_rates_between(engine, currency, first - _RATE_LOOKBACK, today)
            for currency in currencies - {PLN}
        },
        first,
        today,
        load_bond_data(engine),
        Accruals(list_deposits(engine), tax_rates_of(list_accounts(engine)), transactions),
    )


class PortfolioHistory:
    """``today`` is injectable for tests, and so is ``compute``, which runs ``daily_history`` (by default in
    NiceGUI's process pool, ``run.cpu_bound``)."""

    def __init__(
        self,
        engine: Engine,
        quotes: QuoteHistory,
        rates: NbpRates,
        today: Callable[[], date] = date.today,
        compute: Compute | None = None,
    ) -> None:
        self.engine = engine
        self.quotes = quotes
        self.rates = rates
        self.today = today
        self.compute = compute
        self._cached: list[DayValue] | None = None
        # Counts the invalidations, so that a computation started before one never caches its outdated result
        self._generation = 0

    def fetch(self, progress: Callable[[int, int], None] = lambda done, total: None) -> HistoryFetch:
        """Fetch the days still missing from each traded Instrument's first Transaction and each foreign currency's
        first one, and for each benchmark Instrument (issue #91) from the first Transaction, up to yesterday;
        ``progress(done, total)`` follows each Instrument and currency. A failure is recorded and the rest goes on;
        the next fetch tries the missing days again."""
        transactions = list_transactions(self.engine)
        firsts: dict[int, date] = {}
        currencies: dict[str, date] = {}
        for t in transactions:
            if t.instrument_id is not None:
                firsts[t.instrument_id] = min(t.date, firsts.get(t.instrument_id, t.date))
            if t.cash_currency != PLN:
                currencies[t.cash_currency] = min(t.date, currencies.get(t.cash_currency, t.date))
        if transactions:
            start = min(t.date for t in transactions)
            for benchmark in list_benchmarks(self.engine):
                if benchmark.instrument_id is not None:
                    firsts[benchmark.instrument_id] = start
        currencies |= {
            instrument.quote_currency: min(firsts[instrument.id], currencies.get(instrument.quote_currency, date.max))
            for instrument in list_instruments(self.engine)
            if instrument.id in firsts and instrument.quote_currency != PLN
        }
        yesterday = self.today() - ONE_DAY
        total, done = len(firsts) + len(currencies), 0
        failed = HistoryFetch()
        for instrument_id, first in firsts.items():
            try:
                self.quotes.between(instrument_id, first, yesterday)
            except PriceSourceError as exc:
                failed.instruments[instrument_id] = str(exc)
            done += 1
            progress(done, total)
        for currency, first in currencies.items():
            try:
                self.rates.history(currency, first, yesterday)
            except MissingNbpRateError as exc:
                failed.currencies[currency] = str(exc)
            done += 1
            progress(done, total)
        self.invalidate()
        return failed

    def inputs(self) -> HistoryInputs | None:
        """What History is computed from, read from the cache alone; ``None`` without any Transaction."""
        return history_inputs(self.engine, self.today())

    async def values(self) -> list[DayValue]:
        """Each day's value from the first Transaction to today, computed once and then kept until ``invalidate``."""
        if self._cached is not None:
            return self._cached
        generation = self._generation
        inputs = self.inputs()
        values: list[DayValue] = []
        if inputs is not None:
            compute = self.compute or _cpu_bound
            values = await compute(
                daily_history,
                inputs.transactions,
                inputs.instruments,
                inputs.prices,
                inputs.rates,
                inputs.first,
                inputs.last,
                inputs.bonds,
                inputs.accruals,
            )
        if generation == self._generation:
            self._cached = values
        return values

    @property
    def computed(self) -> list[DayValue] | None:
        """History computed since the last ``invalidate``, ``None`` until then (``values`` may still return the days
        of a computation it overtook)."""
        return self._cached

    def invalidate(self) -> None:
        """Forget the computed History, after a Transaction save or a price refresh or fetch."""
        self._cached = None
        self._generation += 1


# A Transaction on a day after a holiday still needs the NBP Rate published before it
_RATE_LOOKBACK = 14 * ONE_DAY


async def _cpu_bound(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
    # None only while the app shuts down
    return await run.cpu_bound(function, *args) or []
