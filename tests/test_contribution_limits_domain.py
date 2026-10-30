"""Contribution Limits (issue #95, spec 8.1): what counts towards each IKE, IKZE and OIPE limit, the Dashboard's bars
and the warning after a save."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.contribution_limits import (
    ContributionLimitError,
    LimitBar,
    contributions,
    limit_bars,
    over_limit,
    over_limit_warning,
    parse_limit,
    remainder_accounts,
    split_over_limit,
)
from financial_app.domain.currencies import NbpRate
from financial_app.domain.transactions import TransactionDraft, TransactionType, cash_transfer

IKE, IKZE, REGULAR = 1, 2, 3


def _account(account_id: int, account_type: AccountType, active: bool = True) -> Account:
    return Account(f"Konto {account_id}", "XTB", account_type, ("PLN",), active=active, id=account_id)


ACCOUNTS = [_account(IKE, AccountType.IKE), _account(IKZE, AccountType.IKZE), _account(REGULAR, AccountType.REGULAR)]


def _deposit(account_id: int, day: date, amount: int) -> TransactionDraft:
    return TransactionDraft(account_id, day, TransactionType.DEPOSIT, Decimal(amount))


def test_deposits_of_the_year_count_towards_their_account_types_limit() -> None:
    transactions = [
        _deposit(IKE, date(2025, 12, 31), 500),
        _deposit(IKE, date(2026, 1, 1), 1000),
        _deposit(IKE, date(2026, 12, 31), 2000),
        _deposit(IKZE, date(2026, 3, 1), 300),
        _deposit(REGULAR, date(2026, 3, 1), 9000),
    ]

    assert contributions(transactions, ACCOUNTS, 2026) == {
        AccountType.IKE: Decimal(3000),
        AccountType.IKZE: Decimal(300),
        AccountType.OIPE: Decimal(0),
    }


OLD_IKE = 4


def test_a_cash_transfer_counts_only_from_an_account_of_another_type() -> None:
    accounts = [*ACCOUNTS, _account(OLD_IKE, AccountType.IKE, active=False)]
    transactions = [
        cash_transfer(REGULAR, date(2026, 2, 1), IKE, Decimal(700)),
        cash_transfer(OLD_IKE, date(2026, 6, 1), IKE, Decimal(5000)),
        cash_transfer(IKE, date(2026, 7, 1), REGULAR, Decimal(100)),
    ]

    assert contributions(transactions, accounts, 2026)[AccountType.IKE] == Decimal(700)


def test_withdrawals_free_up_nothing_and_an_inactive_accounts_deposits_still_count() -> None:
    accounts = [*ACCOUNTS, _account(OLD_IKE, AccountType.IKE, active=False)]
    transactions = [
        _deposit(OLD_IKE, date(2026, 2, 1), 1000),
        TransactionDraft(OLD_IKE, date(2026, 3, 1), TransactionType.WITHDRAWAL, Decimal(400)),
        _deposit(IKE, date(2026, 7, 1), 200),
    ]

    assert contributions(transactions, accounts, 2026)[AccountType.IKE] == Decimal(1200)


LIMITS = {2026: {AccountType.IKE: Decimal(28260), AccountType.IKZE: Decimal(11304), AccountType.OIPE: None}}


def test_total_shows_a_bar_per_type_with_an_active_account_or_a_contribution_this_year() -> None:
    oipe = 5
    accounts = [*ACCOUNTS, _account(oipe, AccountType.OIPE, active=False), _account(6, AccountType.PPK)]
    transactions = [_deposit(IKE, date(2026, 1, 5), 30000), _deposit(oipe, date(2026, 2, 1), 100)]

    bars = limit_bars(transactions, accounts, LIMITS, 2026, account_id=None)

    assert bars == [
        LimitBar(AccountType.IKE, 2026, paid=Decimal(30000), limit=Decimal(28260)),
        LimitBar(AccountType.IKZE, 2026, paid=Decimal(0), limit=Decimal(11304)),
        LimitBar(AccountType.OIPE, 2026, paid=Decimal(100), limit=None),
    ]
    assert (bars[0].left, bars[0].over) == (Decimal(0), Decimal(1740))
    assert (bars[1].left, bars[1].over) == (Decimal(11304), Decimal(0))
    assert bars[2].left is None and bars[2].over is None


def test_an_account_scope_shows_its_types_bar_over_all_its_types_accounts() -> None:
    accounts = [*ACCOUNTS, _account(OLD_IKE, AccountType.IKE, active=False)]
    transactions = [_deposit(IKE, date(2026, 1, 5), 1000), _deposit(OLD_IKE, date(2026, 2, 1), 500)]

    assert limit_bars(transactions, accounts, LIMITS, 2026, account_id=IKE) == [
        LimitBar(AccountType.IKE, 2026, paid=Decimal(1500), limit=Decimal(28260))
    ]
    assert limit_bars(transactions, accounts, LIMITS, 2026, account_id=REGULAR) == []


def test_a_year_without_limits_has_bars_without_a_limit() -> None:
    assert limit_bars([], ACCOUNTS, LIMITS, 2027, account_id=IKZE) == [
        LimitBar(AccountType.IKZE, 2027, Decimal(0), None)
    ]


def test_a_save_warns_once_per_type_and_year_its_contributions_leave_over_the_limit() -> None:
    earlier = _deposit(IKE, date(2026, 1, 5), 28000)
    saved = [
        _deposit(IKE, date(2026, 3, 1), 200),
        _deposit(IKE, date(2026, 4, 1), 300),
        _deposit(IKZE, date(2026, 4, 1), 5),
    ]
    transactions = [earlier, *saved, _deposit(IKE, date(2027, 1, 2), 99999)]

    before = [earlier, transactions[-1]]

    over = over_limit(before, transactions, ACCOUNTS, LIMITS, saved)

    assert over == [LimitBar(AccountType.IKE, 2026, paid=Decimal(28500), limit=Decimal(28260))]
    assert over_limit_warning(over[0]) == "IKE 2026: przekroczono limit wpłat o 240,00\xa0zł."


def test_a_save_counting_towards_no_limit_or_a_year_without_one_never_warns() -> None:
    transactions = [
        _deposit(IKE, date(2026, 1, 5), 30000),
        _deposit(REGULAR, date(2026, 2, 1), 1),
        _deposit(IKE, date(2027, 1, 1), 1),
    ]

    assert over_limit(transactions[:1], transactions, ACCOUNTS, LIMITS, transactions[1:]) == []


def test_a_limit_is_typed_in_pln_and_left_empty_for_none() -> None:
    assert parse_limit("28 260,50 zł") == Decimal("28260.50")
    assert parse_limit("  ") is None
    for text in ("-1", "dużo"):
        with pytest.raises(ContributionLimitError, match="Limit musi być kwotą w zł"):
            parse_limit(text)
    with pytest.raises(ContributionLimitError, match="z dokładnością do grosza"):
        parse_limit("28 260,555")


def test_an_edit_warns_only_when_it_adds_to_a_year_over_its_limit() -> None:
    over = _deposit(IKE, date(2026, 1, 5), 30000)
    commented = TransactionDraft(IKE, date(2026, 1, 5), TransactionType.DEPOSIT, Decimal(30000), "premia")
    lowered = _deposit(IKE, date(2026, 1, 5), 29000)
    raised = _deposit(IKE, date(2026, 1, 5), 31000)

    assert over_limit([over], [commented], ACCOUNTS, LIMITS, [commented, over]) == []
    assert over_limit([over], [lowered], ACCOUNTS, LIMITS, [lowered, over]) == []
    assert over_limit([over], [raised], ACCOUNTS, LIMITS, [raised, over]) == [
        LimitBar(AccountType.IKE, 2026, paid=Decimal(31000), limit=Decimal(28260))
    ]


def test_a_bar_shows_its_used_share_and_a_zero_limit_with_nothing_paid_none() -> None:
    assert LimitBar(AccountType.IKE, 2026, Decimal(7065), Decimal(28260)).share == Decimal("0.25")
    assert LimitBar(AccountType.IKE, 2026, Decimal(0), Decimal(0)).share == 0
    assert LimitBar(AccountType.IKE, 2026, Decimal(5), Decimal(0)).share == 1
    assert LimitBar(AccountType.IKE, 2026, Decimal(5), None).share is None


IKE_BAR = LimitBar(AccountType.IKE, 2026, paid=Decimal(28000), limit=Decimal(28260))


def test_a_deposit_over_the_limit_splits_into_one_up_to_the_limit_and_the_rest_on_another_account() -> None:
    deposit = TransactionDraft(IKE, date(2026, 5, 4), TransactionType.DEPOSIT, Decimal(1000), "premia")

    split = split_over_limit(deposit, IKE_BAR, REGULAR)

    assert split is not None
    assert split.within == TransactionDraft(IKE, date(2026, 5, 4), TransactionType.DEPOSIT, Decimal(260), "premia")
    assert split.remainder == TransactionDraft(
        REGULAR, date(2026, 5, 4), TransactionType.DEPOSIT, Decimal(740), "premia (nadwyżka ponad limit IKE 2026)"
    )
    assert split.deposits == [split.within, split.remainder]
    assert IKE_BAR.paid + split.within.actual_amount == IKE_BAR.limit


def test_a_deposit_with_the_limit_used_up_moves_whole_and_one_within_it_does_not_split() -> None:
    full = LimitBar(AccountType.IKE, 2026, paid=Decimal(28260), limit=Decimal(28260))
    whole = split_over_limit(_deposit(IKE, date(2026, 5, 4), 500), full, REGULAR)
    assert whole is not None and whole.within is None
    assert whole.deposits == [
        TransactionDraft(
            REGULAR, date(2026, 5, 4), TransactionType.DEPOSIT, Decimal(500), "Nadwyżka ponad limit IKE 2026"
        )
    ]

    assert split_over_limit(_deposit(IKE, date(2026, 5, 4), 260), IKE_BAR, REGULAR) is None
    no_limit = LimitBar(AccountType.OIPE, 2026, paid=Decimal(0), limit=None)
    assert split_over_limit(_deposit(IKE, date(2026, 5, 4), 999999), no_limit, REGULAR) is None


def test_a_foreign_currency_deposit_is_not_split() -> None:
    rate = NbpRate("EUR", Decimal("4.2"), date(2026, 5, 1), "083/A/NBP/2026")
    euro = TransactionDraft(
        IKE,
        date(2026, 5, 4),
        TransactionType.DEPOSIT,
        Decimal(1050),
        cash_currency="EUR",
        nbp_rate=rate,
        quantity=Decimal(250),
    )

    assert split_over_limit(euro, IKE_BAR, REGULAR) is None


def test_the_rest_goes_to_an_active_unlimited_pln_account_the_last_deposited_into_first() -> None:
    other, ppk, closed, euro = 5, 6, 7, 8
    accounts = [
        *ACCOUNTS,
        _account(other, AccountType.OTHER),
        _account(ppk, AccountType.PPK),
        _account(closed, AccountType.REGULAR, active=False),
        Account("Euro", "XTB", AccountType.REGULAR, ("EUR",), id=euro),
    ]
    assert [a.id for a in remainder_accounts(accounts, [])] == [REGULAR, other]

    deposits = [_deposit(other, date(2026, 1, 2), 100), _deposit(REGULAR, date(2025, 1, 2), 100)]
    assert [a.id for a in remainder_accounts(accounts, deposits)] == [other, REGULAR]
