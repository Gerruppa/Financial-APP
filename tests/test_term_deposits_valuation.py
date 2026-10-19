"""Term Deposits in the value of their Account (issue #160): the Dashboard and History count the interest accrued net
of Belka, and a save taking the Account's cash below the capital of its running deposits warns."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.dashboard import dashboard
from financial_app.domain.portfolio_history import CASH_CLASS, daily_history
from financial_app.domain.save_warnings import save_warnings
from financial_app.domain.term_deposits import (
    Accruals,
    AccruedInterest,
    Capitalization,
    TermDeposit,
    TermUnit,
    tax_rates_of,
)
from financial_app.domain.transactions import (
    Transaction,
    TransactionDraft,
    TransactionType,
    deposit_or_withdrawal,
    dividend,
)

SAVINGS = Account("Lokaty mBank", "mBank", AccountType.DEPOSIT, ("PLN",), id=1)
MONTHLY = TermDeposit(
    id=1,
    account_id=1,
    name="Lokata 3M",
    principal=Decimal(10000),
    start_date=date(2026, 1, 15),
    term_count=3,
    term_unit=TermUnit.MONTHS,
    annual_rate=Decimal(6),
    capitalization=Capitalization.MONTHLY,
)


def saved(draft: TransactionDraft, transaction_id: int) -> Transaction:
    return Transaction(**{**vars(draft), "id": transaction_id})


def paid_in(amount: int = 10000, day: date = date(2026, 1, 15)) -> Transaction:
    return saved(deposit_or_withdrawal(1, day, TransactionType.DEPOSIT, Decimal(amount)), 1)


def test_the_dashboard_counts_the_accrued_interest_net_in_the_value_and_gross_as_interest() -> None:
    # On 01.03.2026 the first month whole and 14 days of the second: 74,07 zł gross, 14,07 zł Belka
    accrued = {1: AccruedInterest(Decimal("74.07"), Decimal("14.07"))}

    board = dashboard([paid_in()], [SAVINGS], {}, {}, {}, None, accrued=accrued)

    assert board.totals.value == Decimal("10060.00")
    assert board.accounts[0].totals.value == Decimal("10060.00")
    sources = board.sources
    assert (sources.interest, sources.taxes, sources.price) == (Decimal("74.07"), Decimal("-14.07"), Decimal(0))


def test_history_values_the_accrued_interest_each_day_and_the_confirmed_interest_moves_it_into_the_cash() -> None:
    interest = saved(
        replace(
            dividend(1, date(2026, 2, 15), Decimal("50.96"), Decimal("9.68")),
            term_deposit_id=1,
            term_deposit_period=date(2026, 2, 15),
        ),
        2,
    )
    transactions = [paid_in(), interest]
    accruals = Accruals([MONTHLY], tax_rates_of([SAVINGS]), transactions)

    days = daily_history(transactions, {}, {}, {}, date(2026, 2, 14), date(2026, 2, 16), accruals=accruals)

    # 30 days: 49,315… → 49,32 less 9,37; then the 41,28 paid in; then 1 day of 10 041,28: 1,65 less 0,31
    assert [day.accounts[1] for day in days] == [Decimal("10039.95"), Decimal("10041.28"), Decimal("10042.62")]
    assert days[0].classes[CASH_CLASS] == Decimal("10039.95")
    assert [day.net_deposits for day in days] == [Decimal(10000)] * 3


def test_a_withdrawal_reaching_the_capital_of_a_running_deposit_warns_and_one_leaving_it_does_not() -> None:
    before = [paid_in()]
    taken = saved(deposit_or_withdrawal(1, date(2026, 3, 1), TransactionType.WITHDRAWAL, Decimal(500)), 2)

    warned = save_warnings(before, [*before, taken], [SAVINGS], [], [], {}, deposits=[MONTHLY])
    assert warned.messages("Zapisano") == [
        "Zapisano, ale gotówka konta Lokaty mBank 01.03.2026 (9 500,00 zł) jest mniejsza niż kapitał jej lokat "
        "(10 000,00 zł). Jeśli lokata została zerwana, zaznacz to w zakładce Dochód stały."
    ]

    richer = [paid_in(20000)]
    assert not save_warnings(richer, [*richer, taken], [SAVINGS], [], [], {}, deposits=[MONTHLY]).any
