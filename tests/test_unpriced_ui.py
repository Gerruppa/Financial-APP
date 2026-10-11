"""The "Instrumenty bez wyceny" list in Ustawienia (issue #40), without a browser."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.prices import YAHOO, PriceSourceError, Quote
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument
from financial_app.persistence.transactions import add_transaction
from financial_app.ui.shell import build_shell

AKCJE_POLSKIE = 2
OBLIGACJE_SKARBOWE_POLSKIE = 4


class FakeYahoo:
    name = YAHOO

    def __init__(self, prices: dict[str, str]) -> None:
        self.prices = prices

    def new_refresh(self) -> None:
        pass

    def quote(self, symbol: str, currency: str) -> Quote:
        if symbol not in self.prices:
            raise PriceSourceError(f"Yahoo nie zna symbolu „{symbol}”.")
        return Quote(Decimal(self.prices[symbol]), currency, date(2026, 10, 9), YAHOO)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _held(engine: Engine, draft: InstrumentDraft) -> None:
    """10 units of a new Instrument bought for 400 zł on a new Account."""
    account = add_account(engine, AccountDraft(f"Konto {draft.name}", "XTB", AccountType.REGULAR, ("PLN",)))
    instrument = add_instrument(engine, draft)
    add_transaction(engine, TransactionDraft(account.id, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(1000)))
    add_transaction(
        engine, buy_or_sell(account.id, date(2026, 1, 5), TransactionType.BUY, instrument.id, Decimal(10), Decimal(40))
    )


async def test_a_held_instrument_without_a_source_symbol_is_listed_and_opens_its_dialog(engine: Engine) -> None:
    _held(engine, InstrumentDraft("PZU", AKCJE_POLSKIE, "PLN", "GPW"))
    add_instrument(engine, InstrumentDraft("Niekupiony", AKCJE_POLSKIE, "PLN"))
    _held(engine, InstrumentDraft("EDO0336", OBLIGACJE_SKARBOWE_POLSKIE, "PLN"))

    async with user_simulation(lambda: build_shell(engine, sources={YAHOO: FakeYahoo({})})) as user:
        await user.open("/ustawienia")
        with user.scope(marker="unpriced"):
            await user.should_see("PZU")
            await user.should_see("bez źródła")
            await user.should_not_see("Niekupiony")
            await user.should_not_see("EDO0336")
        user.find(marker="unpriced-instrument").click()
        with user.scope(marker="instrument-dialog"):
            await user.should_see("Edytuj instrument")
        assert user.find(marker="instrument-name", kind=ui.input).elements.pop().value == "PZU"


async def test_a_failing_instrument_is_listed_with_the_reason_and_leaves_after_a_fixed_symbol_refreshes(
    engine: Engine,
) -> None:
    _held(engine, InstrumentDraft("PZU", AKCJE_POLSKIE, "PLN", "GPW", source_symbols={YAHOO: "PZU"}))
    sources = {YAHOO: FakeYahoo({"PZU.WA": "45.12"})}

    async with user_simulation(lambda: build_shell(engine, sources=sources)) as user:
        await user.open("/ustawienia")
        with user.scope(marker="unpriced"):
            await user.should_see("czeka na odświeżenie wycen")
        user.find(marker="refresh-prices").click()
        with user.scope(marker="unpriced"):
            await user.should_see("Yahoo: Yahoo nie zna symbolu „PZU”.")

        user.find(marker="unpriced-instrument").click()
        user.find(marker="instrument-symbol-yahoo").clear().type("PZU.WA")
        with user.scope(marker="instrument-dialog"):
            user.find("Zapisz").click()
        await user.should_not_see(marker="instrument-dialog")
        with user.scope(marker="unpriced"):
            await user.should_see("PZU")  # the new symbol is not fetched yet
        user.find(marker="refresh-prices").click()
        with user.scope(marker="unpriced"):
            await user.should_see("Każdy instrument z otwartą pozycją ma wycenę automatyczną.")
            await user.should_not_see("PZU")
