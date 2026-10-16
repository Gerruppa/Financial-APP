"""Deleting an Account nothing names any more, and the "+" left out of Ustawienia (L-28)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountError, AccountHolders, AccountType
from financial_app.domain.strategy import Strategy
from financial_app.domain.transactions import TransactionDraft, TransactionType, cash_transfer
from financial_app.persistence.accounts import account_holders, add_account, delete_account, list_accounts
from financial_app.persistence.db import init_db
from financial_app.persistence.settings import VIEW_SCOPE, XTB_ACCOUNT, load_setting, save_setting
from financial_app.persistence.strategies import save_strategy
from financial_app.persistence.transactions import add_transaction
from financial_app.ui.shell import build_shell


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _account(engine: Engine, name: str) -> int:
    return add_account(engine, AccountDraft(name, "", AccountType.REGULAR, ("PLN",))).id


def _scope_label(user: User) -> str:
    [switcher] = user.find(marker="view-scope").elements
    assert isinstance(switcher, ui.button)
    return str(switcher.text)


def _deposit(engine: Engine, account_id: int) -> None:
    add_transaction(engine, TransactionDraft(account_id, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(1000)))


def test_nothing_holding_an_account_gives_no_refusal() -> None:
    assert AccountHolders().refusal("mBank") is None


def test_the_refusal_names_everything_holding_the_account() -> None:
    holders = AccountHolders(transactions=2, transfers_in=1, strategy=True, xtb_accounts=("51234",))

    assert holders.refusal("XTB IKE") == (
        "Nie można usunąć konta „XTB IKE”: ma 2 transakcje, jest celem 1 przelewu, ma własną strategię inwestycyjną, "
        "jest przypisane do rachunku XTB 51234 w imporcie. Aby je ukryć, wyłącz „Aktywne”."
    )


def test_an_account_without_anything_is_deleted_and_a_scope_on_it_forgotten(engine: Engine) -> None:
    kept = _account(engine, "mBank")
    gone = _account(engine, "Pomyłka")
    save_setting(engine, VIEW_SCOPE, str(gone))

    delete_account(engine, gone)

    assert [a.id for a in list_accounts(engine)] == [kept]
    assert load_setting(engine, VIEW_SCOPE) is None


def test_an_account_with_transactions_or_a_transfer_in_is_kept(engine: Engine) -> None:
    source = _account(engine, "mBank")
    target = _account(engine, "XTB")
    _deposit(engine, source)
    add_transaction(engine, cash_transfer(source, date(2026, 8, 4), target, Decimal(100)))

    with pytest.raises(AccountError, match="ma 2 transakcje"):
        delete_account(engine, source)
    with pytest.raises(AccountError, match="jest celem 1 przelewu"):
        delete_account(engine, target)
    assert len(list_accounts(engine)) == 2


def test_an_account_with_its_own_strategy_or_an_xtb_mapping_is_kept(engine: Engine) -> None:
    ike = _account(engine, "XTB IKE")
    save_strategy(engine, Strategy(ike))
    save_setting(engine, XTB_ACCOUNT + "51234", str(ike))
    save_setting(engine, XTB_ACCOUNT + "60000", str(ike + 1))

    assert account_holders(engine, ike) == AccountHolders(strategy=True, xtb_accounts=("51234",))
    with pytest.raises(AccountError, match="strategię"):
        delete_account(engine, ike)


async def test_the_account_dialog_deletes_an_account_after_confirming(engine: Engine) -> None:
    _account(engine, "Pomyłka")
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-account").click()
        user.find(marker="delete-account").click()

        await user.should_see("Usunąć konto „Pomyłka”?")
        user.find(marker="confirm-delete-account").click()

        with user.scope(marker="accounts"):
            await user.should_see("Nie dodano jeszcze żadnego konta.")
    assert list_accounts(engine) == []


async def test_the_account_dialog_says_what_holds_an_account(engine: Engine) -> None:
    _deposit(engine, _account(engine, "mBank"))
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-account").click()
        user.find(marker="delete-account").click()

        await user.should_see("Nie można usunąć konta „mBank”: ma 1 transakcję.")
        await user.should_not_see(marker="confirm-delete-account")
    assert len(list_accounts(engine)) == 1


async def test_a_new_account_has_no_delete_button(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find("Dodaj konto").click()

        await user.should_see("Nowe konto")
        await user.should_not_see(marker="delete-account")


async def test_deleting_the_account_in_scope_goes_back_to_total(engine: Engine) -> None:
    gone = _account(engine, "Pomyłka")
    save_setting(engine, VIEW_SCOPE, str(gone))
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        assert _scope_label(user) == "Pomyłka"
        user.find(marker="edit-account").click()
        user.find(marker="delete-account").click()
        user.find(marker="confirm-delete-account").click()

        await user.should_see("Nie dodano jeszcze żadnego konta.")
        assert _scope_label(user) == "Total"
    assert load_setting(engine, VIEW_SCOPE) == "total"


async def test_the_add_button_is_not_shown_on_ustawienia(engine: Engine) -> None:
    _account(engine, "mBank")
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        await user.should_not_see(marker="add-transaction")

        await user.open("/transakcje")
        await user.should_see(marker="add-transaction")
