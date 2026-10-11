"""Physical metals with a weight per unit and a Buyback Spread (issue #34): the Instrument dialog and the Portfolio,
without a browser or the network."""

import json
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.prices import YAHOO, PriceSourceError, Quote
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_instruments
from financial_app.persistence.transactions import add_transaction
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
TODAY = date(2026, 1, 8)
FRIDAY = date(2026, 1, 2)
METALE = 8
# Whatever window is asked for, the NBP answers with Monday 5 January 2026
NBP_ANSWER = json.dumps(
    {"table": "A", "code": "USD", "rates": [{"no": "002/A/NBP/2026", "effectiveDate": "2026-01-05", "mid": 3.6045}]}
)
USD_RATE = NbpRate("USD", Decimal("3.6045"), date(2026, 1, 5), "002/A/NBP/2026")


class FakeYahoo:
    name = YAHOO

    def new_refresh(self) -> None:
        pass

    def quote(self, symbol: str, currency: str) -> Quote:
        if symbol != "GC=F":
            raise PriceSourceError(f"Yahoo nie zna symbolu „{symbol}”.")
        return Quote(Decimal(2400), currency, FRIDAY, YAHOO)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _shell(engine: Engine) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: NBP_ANSWER, today=lambda: TODAY), {YAHOO: FakeYahoo()})


@pytest.fixture
async def user(engine: Engine) -> AsyncIterator[User]:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/ustawienia")
        yield user


def _held_coin(engine: Engine, grams: str | None, spread: str | None) -> None:
    """One gold coin with the Yahoo symbol GC=F, bought on an IKE."""
    account = add_account(engine, AccountDraft("mBank IKE", "mBank", AccountType.IKE, ("PLN",)))
    coin = add_instrument(
        engine,
        InstrumentDraft(
            "Krugerrand",
            METALE,
            "USD",
            source_symbols={YAHOO: "GC=F"},
            metal_grams=None if grams is None else Decimal(grams),
            buyback_spread_percent=None if spread is None else Decimal(spread),
        ),
    )
    add_transaction(engine, TransactionDraft(account.id, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(20000)))
    add_transaction(
        engine,
        buy_or_sell(
            account.id, date(2026, 1, 7), TransactionType.BUY, coin.id, Decimal(1), Decimal(2300), nbp_rate=USD_RATE
        ),
    )


async def test_user_gives_an_instrument_its_metal_weight_and_buyback_spread(user: User, engine: Engine) -> None:
    user.find("Dodaj instrument").click()
    for marker, text in {
        "instrument-name": "Krugerrand",
        "instrument-currency": "USD",
        "instrument-metal-grams": "31,1034768",
        "instrument-buyback-spread": "5",
    }.items():
        user.find(marker=marker).clear().type(text)
    with user.scope(marker="instrument-dialog"):
        user.find(marker="instrument-class").click()
        user.find("Metale i surowce").click()
    user.find("Zapisz").click()

    with user.scope(marker="instruments"):
        await user.should_see(f"31,1034768{NBSP}g")
        await user.should_see(f"spread odkupu 5,00{NBSP}%")
    [saved] = list_instruments(engine)
    assert (saved.metal_grams, saved.buyback_spread_percent) == (Decimal("31.1034768"), Decimal(5))
    user.find(marker="edit-instrument").click()
    await user.should_see("31,1034768")


async def test_an_invalid_metal_weight_is_reported_and_not_saved(user: User, engine: Engine) -> None:
    user.find("Dodaj instrument").click()
    user.find(marker="instrument-name").clear().type("Sztabka")
    user.find(marker="instrument-metal-grams").clear().type("sto")
    with user.scope(marker="instrument-dialog"):
        user.find(marker="instrument-class").click()
        user.find("Metale i surowce").click()
    user.find("Zapisz").click()

    await user.should_see("Waga metalu musi być liczbą")
    assert list_instruments(engine) == []


async def test_a_one_ounce_coin_is_valued_at_95_percent_of_spot_with_the_spot_beside_it(engine: Engine) -> None:
    _held_coin(engine, "31.1034768", "5")

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/portfolio")
        user.find(marker="refresh-prices").click()

        with user.scope(marker="portfolio"):
            await user.should_see(f"2{NBSP}280,00{NBSP}USD")  # 95% of the spot
            await user.should_see(f"spot 2{NBSP}400,00{NBSP}USD/oz")
            await user.should_see(f"8{NBSP}218,26{NBSP}zł")  # 2 280 USD × 3,6045
            await user.should_see(f"spot 8{NBSP}650,80{NBSP}zł")  # 2 400 USD × 3,6045


async def test_without_a_weight_the_quote_is_the_unit_price(engine: Engine) -> None:
    _held_coin(engine, None, None)

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/portfolio")
        user.find(marker="refresh-prices").click()

        with user.scope(marker="portfolio"):
            await user.should_see(f"8{NBSP}650,80{NBSP}zł")  # 2 400 USD × 3,6045
            await user.should_not_see("spot")
