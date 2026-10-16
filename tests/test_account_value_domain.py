"""An Account's value and result today (issue #109): the one definition the Portfolio and the Dashboard share."""

from datetime import date
from decimal import Decimal

from financial_app.domain.account_value import AccountValue, account_value, is_listed
from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.lots import foreign_cash, open_positions
from financial_app.domain.transactions import (
    TransactionDraft,
    TransactionType,
    buy_or_sell,
    cash_balances,
    currency_exchange,
)

IKE, XTB = 1, 2
PZU = 10


def _account(account_id: int, *, exclude_fx_result: bool = False, active: bool = True) -> Account:
    return Account(
        "Konto", "", AccountType.REGULAR, ("PLN",), exclude_fx_result=exclude_fx_result, active=active, id=account_id
    )


def _trades(account: int = IKE) -> list[TransactionDraft]:
    """2000 PLN in; 10 PZU at 50 with a 5 PLN fee; 250 USD for 1000 PLN, 100 of them back for 440 PLN (40 realised)."""
    return [
        TransactionDraft(account, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(2000)),
        buy_or_sell(account, date(2026, 1, 2), TransactionType.BUY, PZU, Decimal(10), Decimal(50), Decimal(5)),
        currency_exchange(account, date(2026, 1, 2), "USD", Decimal(250), Decimal(1000)),
        currency_exchange(account, date(2026, 1, 3), "USD", Decimal(100), Decimal(440), to_pln=True),
    ]


def _value_of(
    account: Account, transactions: list[TransactionDraft], prices: dict[int, Decimal], rates: dict[str, Decimal]
) -> AccountValue:
    return account_value(
        account,
        cash_balances(transactions).get(account.id, Decimal(0)),
        open_positions(transactions),
        foreign_cash(transactions),
        prices,
        rates,
    )


def test_value_is_cash_positions_at_price_and_foreign_cash_at_the_rate() -> None:
    # 935 PLN cash + 10 PZU at 60 + 150 USD at 4.20
    value = _value_of(_account(IKE), _trades(), {PZU: Decimal(60)}, {"USD": Decimal("4.2")})

    assert value.cash == Decimal(935)
    assert value.open_positions == Decimal(1230)
    assert value.value == Decimal(2165)


def test_result_is_the_positions_result_with_the_fx_result_of_foreign_cash() -> None:
    # PZU: 600 - 505; USD: 30 unrealised (150 at 4.20 cost 600) and 40 realised
    value = _value_of(_account(IKE), _trades(), {PZU: Decimal(60)}, {"USD": Decimal("4.2")})

    assert value.unrealized == Decimal(125)
    assert value.realized_fx == Decimal(40)
    assert value.result == Decimal(165)
    assert value.fx == Decimal(70)


def test_an_account_excluding_its_fx_result_still_shows_it_but_leaves_it_out_of_the_result() -> None:
    value = _value_of(_account(IKE, exclude_fx_result=True), _trades(), {PZU: Decimal(60)}, {"USD": Decimal("4.2")})

    assert value.value == Decimal(2165)
    assert value.unrealized == Decimal(95)
    assert value.realized_fx == Decimal(0)
    assert value.result == Decimal(95)
    assert value.fx == Decimal(70)


def test_without_a_price_or_rate_holdings_count_at_cost_and_add_nothing_unrealised() -> None:
    # 935 PLN cash + PZU at its cost of 505 + 150 USD at their cost of 600
    value = _value_of(_account(IKE), _trades(), {}, {})

    assert value.value == Decimal(2040)
    assert value.unrealized == Decimal(0)
    assert value.result == Decimal(40)
    assert value.fx == Decimal(40)


def test_only_the_accounts_own_holdings_count() -> None:
    transactions = _trades(IKE) + [TransactionDraft(XTB, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(300))]

    value = _value_of(_account(XTB), transactions, {PZU: Decimal(60)}, {"USD": Decimal("4.2")})

    assert (value.value, value.result) == (Decimal(300), Decimal(0))


def test_an_inactive_account_is_listed_only_while_it_holds_something() -> None:
    emptied = [
        TransactionDraft(IKE, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(100)),
        TransactionDraft(IKE, date(2026, 1, 2), TransactionType.WITHDRAWAL, Decimal(100)),
    ]
    inactive = _account(IKE, active=False)

    assert not is_listed(inactive, _value_of(inactive, emptied, {}, {}))
    assert is_listed(inactive, _value_of(inactive, _trades(), {}, {}))
    assert is_listed(_account(IKE), _value_of(_account(IKE), emptied, {}, {}))
