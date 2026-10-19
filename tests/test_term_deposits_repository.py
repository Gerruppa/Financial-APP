"""Saving Term Deposits and confirming their Drafts (issue #160)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.term_deposits import (
    Capitalization,
    DepositMaturityDraft,
    InterestDraft,
    TermDepositDraft,
    TermDepositError,
    TermUnit,
)
from financial_app.persistence.accounts import add_account, delete_account
from financial_app.persistence.db import init_db
from financial_app.persistence.deposit_drafts import confirm_interest, pending_deposit_drafts
from financial_app.persistence.reset import clear_portfolio
from financial_app.persistence.term_deposits import (
    add_deposit,
    close_deposit,
    delete_deposit,
    list_deposits,
    renew_deposit,
    update_deposit,
)
from financial_app.persistence.transactions import delete_transaction, list_transactions


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def account(engine: Engine) -> int:
    return add_account(engine, AccountDraft("Lokaty", "mBank", AccountType.DEPOSIT, ("PLN",))).id


def three_months(account_id: int, **fields: object) -> TermDepositDraft:
    values: dict[str, object] = {
        "account_id": account_id,
        "name": "Lokata 3M",
        "principal": Decimal(10000),
        "start_date": date(2026, 1, 15),
        "term_count": 3,
        "term_unit": TermUnit.MONTHS,
        "annual_rate": Decimal("6.5"),
        "capitalization": Capitalization.AT_MATURITY,
    }
    values.update(fields)
    return TermDepositDraft(**values)  # type: ignore[arg-type]


def test_a_deposit_is_saved_and_listed_with_its_fields(engine: Engine, account: int) -> None:
    saved = add_deposit(engine, three_months(account, renew=True))

    assert list_deposits(engine) == [saved]
    assert (saved.principal, saved.annual_rate, saved.capitalization, saved.renew) == (
        Decimal(10000),
        Decimal("6.5"),
        Capitalization.AT_MATURITY,
        True,
    )


def test_a_deposit_is_only_held_by_a_deposit_account_holding_pln(engine: Engine) -> None:
    ike = add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN",))).id
    euro = add_account(engine, AccountDraft("Lokaty EUR", "mBank", AccountType.DEPOSIT, ("EUR",))).id

    with pytest.raises(TermDepositError, match="tylko na koncie typu Lokata / oszczędności"):
        add_deposit(engine, three_months(ike))
    with pytest.raises(TermDepositError, match="w złotych"):
        add_deposit(engine, three_months(euro))


def test_an_edited_deposit_keeps_its_id(engine: Engine, account: int) -> None:
    saved = add_deposit(engine, three_months(account))

    edited = update_deposit(engine, saved.id, three_months(account, name="Lokata zimowa"))

    assert (edited.id, edited.name) == (saved.id, "Lokata zimowa")
    assert list_deposits(engine) == [edited]


def test_confirming_an_interest_draft_saves_interest_linked_to_its_period(engine: Engine, account: int) -> None:
    add_deposit(engine, three_months(account))

    (interest, maturity) = pending_deposit_drafts(engine, date(2026, 4, 20))
    assert isinstance(interest, InterestDraft) and isinstance(maturity, DepositMaturityDraft)
    confirm_interest(engine, interest)

    (saved,) = list_transactions(engine)
    assert (saved.date, saved.gross, saved.term_deposit_period) == (
        date(2026, 4, 15),
        interest.period.gross,
        date(2026, 4, 15),
    )
    assert pending_deposit_drafts(engine, date(2026, 4, 20)) == [maturity]
    # Deleting the interest makes its period a Draft again
    delete_transaction(engine, saved.id)
    assert len(pending_deposit_drafts(engine, date(2026, 4, 20))) == 2


def test_ending_a_deposit_closes_it_on_maturity_and_renewing_starts_the_next_one_there(
    engine: Engine, account: int
) -> None:
    ended = add_deposit(engine, three_months(account))
    renewed = add_deposit(engine, three_months(account, name="Lokata odnawialna", renew=True))
    drafts = [d for d in pending_deposit_drafts(engine, date(2026, 4, 20)) if isinstance(d, DepositMaturityDraft)]
    by_name = {d.deposit.name: d for d in drafts}

    close_deposit(engine, ended.id, by_name["Lokata 3M"].due)
    new = renew_deposit(engine, by_name["Lokata odnawialna"], Decimal(6))

    assert [d.closed_on for d in list_deposits(engine) if d.id in (ended.id, renewed.id)] == [
        date(2026, 4, 15),
        date(2026, 4, 15),
    ]
    assert (new.start_date, new.principal, new.annual_rate, new.renew) == (
        date(2026, 4, 15),
        by_name["Lokata odnawialna"].final_capital,
        Decimal(6),
        True,
    )
    assert not [d for d in pending_deposit_drafts(engine, date(2026, 4, 20)) if isinstance(d, DepositMaturityDraft)]


def test_a_deposit_is_broken_before_maturity(engine: Engine, account: int) -> None:
    saved = add_deposit(engine, three_months(account))

    close_deposit(engine, saved.id, date(2026, 3, 1))

    assert list_deposits(engine)[0].closed_on == date(2026, 3, 1)
    assert pending_deposit_drafts(engine, date(2026, 5, 1)) == []
    with pytest.raises(TermDepositError, match="przed założeniem"):
        close_deposit(engine, saved.id, date(2026, 1, 1))


def test_a_deleted_deposit_leaves_its_interest_unlinked(engine: Engine, account: int) -> None:
    saved = add_deposit(engine, three_months(account))
    (interest, _) = pending_deposit_drafts(engine, date(2026, 4, 20))
    assert isinstance(interest, InterestDraft)
    confirm_interest(engine, interest)

    delete_deposit(engine, saved.id)

    assert list_deposits(engine) == []
    (kept,) = list_transactions(engine)
    assert (kept.term_deposit_id, kept.term_deposit_period) == (None, None)


def test_deleting_the_account_or_clearing_the_data_deletes_its_deposits(engine: Engine, account: int) -> None:
    add_deposit(engine, three_months(account))
    delete_account(engine, account)
    assert list_deposits(engine) == []

    other = add_account(engine, AccountDraft("Lokaty 2", "mBank", AccountType.DEPOSIT, ("PLN",))).id
    add_deposit(engine, replace(three_months(other), name="Lokata 2"))
    clear_portfolio(engine)
    assert list_deposits(engine) == []
