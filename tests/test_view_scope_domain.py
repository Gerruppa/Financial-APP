"""The View Scope: Total or one Account, remembered as text, and the Accounts the switcher offers (issue #71, spec
section 5 and 6.1)."""

from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.view_scope import TOTAL, ScopeEntry, parse_scope, scope_entries, scope_setting

IKE, XTB, OLD = 1, 2, 3


def _account(account_id: int, name: str, active: bool = True) -> Account:
    return Account(name, "", AccountType.REGULAR, ("PLN",), active=active, id=account_id)


ACCOUNTS = [_account(IKE, "IKE"), _account(XTB, "XTB"), _account(OLD, "Stare", active=False)]


def test_the_scope_is_stored_as_total_or_the_account_id() -> None:
    assert scope_setting(None) == TOTAL == "total"
    assert scope_setting(IKE) == "1"
    assert parse_scope("1", {IKE, XTB}) == IKE
    assert parse_scope("total", {IKE, XTB}) is None


def test_a_scope_of_a_deleted_account_or_unreadable_falls_back_to_total() -> None:
    assert parse_scope("7", {IKE, XTB}) is None
    assert parse_scope("abc", {IKE}) is None
    assert parse_scope(None, {IKE}) is None


def test_accounts_come_by_value_descending_with_their_share_and_daily_change() -> None:
    history = [
        DayValue(
            date(2026, 1, 1),
            {IKE: Decimal(1000), XTB: Decimal(3000)},
            {},
            Decimal(4000),
            {IKE: Decimal(1000), XTB: Decimal(3000)},
            frozenset(),
        ),
        DayValue(
            date(2026, 1, 2),
            {IKE: Decimal(1100), XTB: Decimal(2900)},
            {},
            Decimal(4000),
            {IKE: Decimal(1000), XTB: Decimal(3000)},
            frozenset(),
        ),
    ]

    assert scope_entries(ACCOUNTS, history) == [
        ScopeEntry(XTB, "XTB", True, Decimal(2900), Decimal("0.725"), Decimal(-100)),
        ScopeEntry(IKE, "IKE", True, Decimal(1100), Decimal("0.275"), Decimal(100)),
        ScopeEntry(OLD, "Stare", False, Decimal(0), Decimal(0), Decimal(0)),
    ]


def test_while_the_history_loads_accounts_come_by_name_without_values() -> None:
    assert scope_entries(ACCOUNTS, None) == [
        ScopeEntry(IKE, "IKE", True, None, None, None),
        ScopeEntry(OLD, "Stare", False, None, None, None),
        ScopeEntry(XTB, "XTB", True, None, None, None),
    ]


def test_an_empty_portfolio_has_no_shares() -> None:
    history = [DayValue(date(2026, 1, 1), {}, {}, Decimal(0), {}, frozenset())]

    assert scope_entries(ACCOUNTS[:1], history) == [ScopeEntry(IKE, "IKE", True, Decimal(0), None, Decimal(0))]
