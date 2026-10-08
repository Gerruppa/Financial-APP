"""Saving Accounts in SQLite (issue #10): add, edit, deactivate, unique names, survives restart."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountError, AccountType
from financial_app.persistence.accounts import add_account, list_accounts, update_account
from financial_app.persistence.db import init_db

XTB = AccountDraft(
    name="XTB",
    broker="XTB",
    account_type=AccountType.REGULAR,
    cash_currencies=("PLN", "USD"),
    fx_conversion_fee_percent=Decimal("0.5"),
    exclude_fx_result=True,
)
IKE = AccountDraft(name="mBank IKE", broker="mBank", account_type=AccountType.IKE, cash_currencies=("PLN",))


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return tmp_path / "app.sqlite3"


@pytest.fixture
def engine(db_file: Path) -> Engine:
    return init_db(db_file)


def test_added_account_is_listed_with_all_its_fields(engine: Engine) -> None:
    saved = add_account(engine, XTB)

    [listed] = list_accounts(engine)
    assert listed == saved
    assert listed.name == "XTB"
    assert listed.broker == "XTB"
    assert listed.account_type is AccountType.REGULAR
    assert listed.cash_currencies == ("PLN", "USD")
    assert listed.fx_conversion_fee_percent == Decimal("0.5")
    assert listed.exclude_fx_result
    assert listed.active


def test_accounts_survive_a_restart(db_file: Path, engine: Engine) -> None:
    add_account(engine, XTB)
    add_account(engine, IKE)
    engine.dispose()

    reopened = init_db(db_file)

    assert [a.name for a in list_accounts(reopened)] == ["mBank IKE", "XTB"]


def test_editing_an_account_changes_its_fields(engine: Engine) -> None:
    saved = add_account(engine, IKE)

    update_account(
        engine,
        saved.id,
        replace(IKE, name="mBank IKE (stare)", cash_currencies=("PLN", "EUR"), fx_conversion_fee_percent=None),
    )

    [listed] = list_accounts(engine)
    assert listed.id == saved.id
    assert listed.name == "mBank IKE (stare)"
    assert listed.cash_currencies == ("PLN", "EUR")
    assert listed.fx_conversion_fee_percent is None


def test_deactivated_account_stays_listed_as_inactive(engine: Engine) -> None:
    saved = add_account(engine, IKE)

    update_account(engine, saved.id, replace(IKE, active=False))

    [listed] = list_accounts(engine)
    assert not listed.active


@pytest.mark.parametrize("name", ["XTB", "xtb", " XTB "])
def test_account_name_must_be_unique(engine: Engine, name: str) -> None:
    add_account(engine, XTB)

    with pytest.raises(AccountError, match="już istnieje"):
        add_account(engine, replace(IKE, name=name))


def test_renaming_onto_another_accounts_name_is_rejected(engine: Engine) -> None:
    add_account(engine, XTB)
    ike = add_account(engine, IKE)

    with pytest.raises(AccountError, match="już istnieje"):
        update_account(engine, ike.id, replace(IKE, name="XTB"))


def test_saving_an_account_under_its_own_name_is_allowed(engine: Engine) -> None:
    saved = add_account(engine, XTB)

    update_account(engine, saved.id, replace(XTB, broker="X-Trade Brokers"))

    assert list_accounts(engine)[0].broker == "X-Trade Brokers"
