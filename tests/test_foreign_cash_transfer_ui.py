"""A Cash Transfer in USD end to end (issue #125), without the network."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from nicegui.testing import User, UserInteraction, user_simulation

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
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


async def test_usd_transfer_goes_to_an_account_holding_usd_at_the_nbp_rate(tmp_path: Path) -> None:
    engine = init_db(tmp_path / "app.sqlite3")
    add_account(engine, AccountDraft("IBKR", "IBKR", AccountType.REGULAR, ("PLN", "USD")))
    revolut = add_account(engine, AccountDraft("Revolut", "Revolut", AccountType.REGULAR, ("USD",))).id
    rates = NbpRates(engine, fetch=lambda url: NBP_ANSWER, today=lambda: TODAY)

    async with user_simulation(lambda: build_shell(engine, rates)) as user:
        await user.open("/transakcje")
        user.find(marker="add-transaction").click()
        _choose(user, "transaction-account", "IBKR")
        _choose(user, "transaction-type", "Transfer gotówki")
        _choose(user, "transaction-cash-currency", "USD")
        user.find(marker="transaction-date").clear().type("07.01.2026")
        user.find(marker="transaction-amount").type("100")
        user.find("Zapisz").click()

        with user.scope(marker="transactions"):
            await user.should_see("IBKR → Revolut")
            await user.should_see(f"100,00{NBSP}USD")
            await user.should_see(f"360,45{NBSP}zł")  # at the NBP Rate 3,6045
    [transfer] = list_transactions(engine)
    assert (transfer.cash_currency, transfer.quantity, transfer.target_account_id) == ("USD", Decimal(100), revolut)
