"""A Buy on an Account without PLN end to end (issue #124), without the network."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from nicegui.testing import User, UserInteraction, user_simulation

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import list_transactions
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell

NBSP = "\xa0"
TODAY = date(2026, 1, 8)
# Whatever window is asked for, the NBP answers with Monday 5 January 2026
NBP_ANSWER = json.dumps(
    {"table": "A", "code": "USD", "rates": [{"no": "002/A/NBP/2026", "effectiveDate": "2026-01-05", "mid": 3.6045}]}
)


def _choose(user: User, marker: str, option: str) -> None:
    user.find(marker=marker).click()
    # Only in that select: the page behind the dialog may show the same name
    UserInteraction(user, set(user.find(marker=marker).elements), option).click()


async def test_buy_on_a_usd_only_account_takes_its_usd_commission_from_the_dollars(tmp_path: Path) -> None:
    engine = init_db(tmp_path / "app.sqlite3")
    add_account(engine, AccountDraft("Revolut", "Revolut", AccountType.REGULAR, ("USD",)))
    add_instrument(engine, InstrumentDraft("Apple", list_asset_classes(engine)[2].id, "USD", manual_price=Decimal(160)))
    rates = NbpRates(engine, fetch=lambda url: NBP_ANSWER, today=lambda: TODAY)

    async with user_simulation(lambda: build_shell(engine, rates)) as user:
        await user.open("/transakcje")
        user.find(marker="add-transaction").click()
        _choose(user, "transaction-type", "Zakup")
        _choose(user, "transaction-instrument", "Apple")
        user.find(marker="transaction-date").clear().type("07.01.2026")
        user.find(marker="transaction-quantity").type("10")
        user.find(marker="transaction-price").type("150,5")
        user.find(marker="transaction-commission").type("2,5")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see(f"-1{NBSP}507,50{NBSP}USD")
    [buy] = list_transactions(engine)
    assert (buy.cash_currency, buy.commission_currency, buy.commission) == ("USD", "USD", Decimal("2.5"))
