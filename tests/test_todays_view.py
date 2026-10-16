"""Today's View state loaded once for the tabs (issue #109), on an in-memory database with fixed NBP Rates."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import MissingNbpRateError, NbpRate
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.prices import YAHOO, Quote
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell, currency_exchange
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import migrate
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.quotes import save_quote
from financial_app.persistence.transactions import add_transaction
from financial_app.sources.todays_view import todays_view

TODAY = date(2026, 3, 2)


class FixedRates:
    """NBP Rates fixed by currency, published the day before ``TODAY``; others are missing."""

    def __init__(self, rates: dict[str, str]) -> None:
        self.rates = rates
        self.asked: list[str] = []

    def today(self) -> date:
        return TODAY

    def latest(self, currency: str) -> NbpRate:
        self.asked.append(currency)
        if currency not in self.rates:
            raise MissingNbpRateError(f"Brak kursu NBP {currency}.")
        return NbpRate(currency, Decimal(self.rates[currency]), TODAY - timedelta(days=1), "test")


@pytest.fixture
def engine() -> Engine:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    migrate(engine)
    return engine


def _account(engine: Engine, currencies: tuple[str, ...] = ("PLN",)) -> int:
    return add_account(engine, AccountDraft("IKE", "Broker", AccountType.IKE, currencies)).id


def _instrument(engine: Engine, name: str, currency: str = "PLN", manual: str | None = None) -> int:
    asset_class = list_asset_classes(engine)[0].id
    price = None if manual is None else Decimal(manual)
    return add_instrument(engine, InstrumentDraft(name, asset_class, currency, manual_price=price)).id


def _deposit(account: int, amount: str) -> TransactionDraft:
    return TransactionDraft(account, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(amount))


def _trade(
    account: int, kind: TransactionType, instrument: int, quantity: str, price: str, day: int
) -> TransactionDraft:
    return buy_or_sell(account, date(2026, 1, day), kind, instrument, Decimal(quantity), Decimal(price))


def test_positions_replay_the_transactions_in_entry_order(engine: Engine) -> None:
    # Two Buys on one day: FIFO sells the one entered first, leaving the Lot bought at 60
    account = _account(engine)
    pzu = _instrument(engine, "PZU")
    for draft in (
        _deposit(account, "2000"),
        _trade(account, TransactionType.BUY, pzu, "10", "50", 5),
        _trade(account, TransactionType.BUY, pzu, "10", "60", 5),
        _trade(account, TransactionType.SELL, pzu, "10", "70", 6),
    ):
        add_transaction(engine, draft)

    view = todays_view(engine, FixedRates({}))

    [position] = view.positions
    assert (position.quantity, position.cost) == (Decimal(10), Decimal(600))
    assert [t.date.day for t in view.transactions] == [2, 5, 5, 6]
    assert view.cash == {account: Decimal(1600)}


def test_held_instruments_are_priced_at_todays_quote_and_nbp_rate(engine: Engine) -> None:
    # 2 AAPL bought at 100 USD (4.00 PLN) quoted at 150 USD; 4.20 PLN per USD today
    account = _account(engine, ("PLN", "USD"))
    aapl = _instrument(engine, "AAPL", "USD")
    _instrument(engine, "MSFT", "USD", manual="300")
    usd = NbpRate("USD", Decimal(4), date(2026, 1, 2), "test")
    add_transaction(engine, _deposit(account, "1000"))
    add_transaction(
        engine,
        buy_or_sell(account, date(2026, 1, 5), TransactionType.BUY, aapl, Decimal(2), Decimal(100), nbp_rate=usd),
    )
    save_quote(engine, aapl, Quote(Decimal(150), "USD", date(2026, 2, 27), YAHOO), datetime(2026, 2, 27, 18))

    view = todays_view(engine, FixedRates({"USD": "4.2"}))

    assert set(view.prices) == {aapl}
    assert view.pln_prices == {aapl: Decimal(630)}
    assert view.rates["USD"] == Decimal("4.2")
    assert view.today == TODAY


def test_an_accounts_value_counts_its_positions_and_foreign_cash_at_todays_prices(engine: Engine) -> None:
    # 400 PLN cash + 10 PZU at the Manual Price of 60 + 100 USD at 4.20
    account = _account(engine, ("PLN", "USD"))
    pzu = _instrument(engine, "PZU", manual="60")
    for draft in (
        _deposit(account, "1300"),
        _trade(account, TransactionType.BUY, pzu, "10", "50", 5),
        currency_exchange(account, date(2026, 1, 5), "USD", Decimal(100), Decimal(400)),
    ):
        add_transaction(engine, draft)

    view = todays_view(engine, FixedRates({"USD": "4.2"}))

    [ike] = view.accounts
    value = view.account_value(ike)
    assert value.value == Decimal(1420)
    assert value.result == Decimal(120)


def test_nbp_rates_are_asked_once_per_currency(engine: Engine) -> None:
    account = _account(engine, ("PLN", "USD"))
    for amount in ("100", "200"):
        add_transaction(engine, currency_exchange(account, date(2026, 1, 5), "USD", Decimal(amount), Decimal(400)))
    rates = FixedRates({})

    view = todays_view(engine, rates)

    assert rates.asked == ["USD"]
    assert "USD" not in view.rates
