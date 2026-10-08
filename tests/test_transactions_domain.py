"""Deposits, Withdrawals and the PLN Cash Balance of each Account (issue #11, spec 3.5)."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.transactions import (
    TransactionDraft,
    TransactionError,
    TransactionType,
    cash_balances,
    lowest_cash_balance,
)

IKE, XTB = 1, 2


def _deposit(account_id: int, amount: str, day: int = 1) -> TransactionDraft:
    return TransactionDraft(account_id, date(2026, 1, day), TransactionType.DEPOSIT, Decimal(amount))


def _withdrawal(account_id: int, amount: str, day: int = 1) -> TransactionDraft:
    return TransactionDraft(account_id, date(2026, 1, day), TransactionType.WITHDRAWAL, Decimal(amount))


def test_account_without_transactions_has_no_balance_entry() -> None:
    assert cash_balances([]) == {}


def test_deposit_increases_the_cash_balance() -> None:
    assert cash_balances([_deposit(IKE, "1000"), _deposit(IKE, "250.50")]) == {IKE: Decimal("1250.50")}


def test_withdrawal_decreases_the_cash_balance() -> None:
    assert cash_balances([_deposit(IKE, "1000"), _withdrawal(IKE, "300")]) == {IKE: Decimal("700")}


def test_balances_are_kept_per_account() -> None:
    balances = cash_balances([_deposit(IKE, "1000"), _deposit(XTB, "500"), _withdrawal(XTB, "200")])

    assert balances == {IKE: Decimal("1000"), XTB: Decimal("300")}


def test_withdrawal_beyond_the_balance_is_allowed_and_goes_negative() -> None:
    # Insufficient cash only warns (spec 3.3), so history can be entered in any order
    assert cash_balances([_withdrawal(IKE, "100")]) == {IKE: Decimal("-100")}


def test_balance_on_a_date_ignores_later_transactions() -> None:
    transactions = [_deposit(IKE, "1000", day=1), _withdrawal(IKE, "400", day=10)]

    assert cash_balances(transactions, on=date(2026, 1, 9)) == {IKE: Decimal("1000")}
    assert cash_balances(transactions, on=date(2026, 1, 10)) == {IKE: Decimal("600")}


def test_transaction_types_have_polish_labels() -> None:
    assert [t.label for t in TransactionType] == ["Wpłata", "Wypłata"]


@pytest.mark.parametrize("amount", ["0", "-5"])
def test_amount_must_be_positive(amount: str) -> None:
    with pytest.raises(TransactionError, match="większa od zera"):
        _deposit(IKE, amount)


def test_amount_is_kept_to_the_grosz() -> None:
    with pytest.raises(TransactionError, match="grosza"):
        _deposit(IKE, "10.005")


def test_comment_is_trimmed() -> None:
    draft = TransactionDraft(IKE, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(1), comment="  premia ")

    assert draft.comment == "premia"


def test_lowest_cash_balance_from_a_date_finds_a_later_dip() -> None:
    transactions = [_deposit(IKE, "1000", day=1), _withdrawal(IKE, "900", day=10), _deposit(IKE, "500", day=20)]

    assert lowest_cash_balance(transactions, IKE, start=date(2026, 1, 5)) == Decimal("100")


def test_backdated_withdrawal_that_breaks_a_later_balance_is_found() -> None:
    transactions = [_deposit(IKE, "100", day=1), _withdrawal(IKE, "80", day=10), _withdrawal(IKE, "50", day=5)]

    assert lowest_cash_balance(transactions, IKE, start=date(2026, 1, 5)) == Decimal("-30")


def test_lowest_cash_balance_ignores_other_accounts() -> None:
    transactions = [_deposit(IKE, "100"), _withdrawal(XTB, "500")]

    assert lowest_cash_balance(transactions, IKE, start=date(2026, 1, 1)) == Decimal("100")
