"""Recurring Rules in Ustawienia and their Drafts in the Transakcje tab and the header (issue #97, spec 3.3.1)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from nicegui.testing.user_interaction import UserInteraction
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.recurring import Frequency, RecurringRuleDraft
from financial_app.domain.transactions import TransactionType, buy_or_sell, deposit_or_withdrawal
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.recurring_rules import add_rule, list_rules, skip_occurrence, skipped_occurrences
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell

NBSP = "\xa0"
# A Thursday; the 10th of October 2026 is a Saturday, so that occurrence falls on Monday 12.10
TODAY = date(2026, 10, 15)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def account(engine: Engine) -> int:
    return add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN",))).id


def _etf(engine: Engine) -> int:
    return add_instrument(engine, InstrumentDraft("ETF X", list_asset_classes(engine)[0].id, "PLN", "GPW")).id


def _deposits(account: int, **fields: object) -> RecurringRuleDraft:
    values: dict[str, object] = {
        "name": "Wpłata IKE",
        "account_id": account,
        "transaction_type": TransactionType.DEPOSIT,
        "amount": Decimal(1000),
        "currency": "PLN",
        "frequency": Frequency.MONTHLY,
        "day_of_month": 10,
        "start_date": date(2026, 9, 1),
    }
    values.update(fields)
    return RecurringRuleDraft(**values)  # type: ignore[arg-type]


def _shell(engine: Engine) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: None, today=lambda: TODAY))


def _type(user: User, marker: str, text: str) -> None:
    field = user.find(marker=marker)
    field.clear()
    field.type(text)


def _value(user: User, marker: str) -> str:
    return str(user.find(marker=marker, kind=ui.input).elements.pop().value)


def _selected(user: User, marker: str) -> object:
    return user.find(marker=marker, kind=ui.select).elements.pop().value


def _choose(user: User, marker: str, value: object) -> None:
    for element in user.find(marker=marker).elements:
        assert isinstance(element, ui.select)
        element.value = value


def _click_in_row(user: User, marker: str, day: str) -> None:
    """Click the button with ``marker`` in the Draft row of ``day``; every row has one."""
    [button] = [
        b
        for b in user.find(marker=marker).elements
        if any(isinstance(e, ui.label) and e.text == day for e in b.parent_slot.parent.default_slot.children)  # type: ignore[union-attr]
    ]
    UserInteraction(user, {button}, None).click()


async def test_a_rule_is_added_in_settings_with_its_next_occurrence(engine: Engine, account: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/ustawienia")
        await user.should_see(marker="recurring-rules")
        user.find(marker="add-recurring-rule").click()
        await user.should_see(marker="rule-name")
        _type(user, "rule-name", "Wpłata IKE")
        _type(user, "rule-amount", "1 000,50")
        _type(user, "rule-day", "10")
        # The start defaults to the next occurrence, so no backlog of Drafts appears
        _type(user, "rule-start", "01.11.2026")
        user.find(marker="save-rule").click()
        await user.should_see(marker="recurring-rule")

        with user.scope(marker="recurring-rule"):
            await user.should_see("Wpłata IKE")
            await user.should_see(f"1{NBSP}000,50{NBSP}zł")
            await user.should_see("co miesiąc, dzień 10")
            await user.should_see("najbliższy 10.11.2026")
    [rule] = list_rules(engine)
    assert (rule.amount, rule.start_date, rule.account_id) == (Decimal("1000.50"), date(2026, 11, 1), account)


async def test_a_rule_is_checked_with_a_polish_message(engine: Engine, account: int) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="add-recurring-rule").click()
        await user.should_see(marker="rule-name")
        _type(user, "rule-amount", "100")
        user.find(marker="save-rule").click()
        await user.should_see("Podaj nazwę reguły.")
        _type(user, "rule-name", "Kupno ETF")
        _choose(user, "rule-type", TransactionType.BUY.value)
        user.find(marker="save-rule").click()
        await user.should_see("Wybierz instrument.")
    assert list_rules(engine) == []


async def test_a_rule_is_switched_off_edited_and_deleted(engine: Engine, account: int) -> None:
    add_rule(engine, _deposits(account))
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="toggle-recurring-rule").click()
        await user.should_see("wyłączona")
        assert not list_rules(engine)[0].active

        user.find(marker="edit-recurring-rule").click()
        _type(user, "rule-name", "IKE co miesiąc")
        user.find(marker="save-rule").click()
        await user.should_see("IKE co miesiąc")

        user.find(marker="delete-recurring-rule").click()
        user.find(marker="confirm-delete-recurring-rule").click()
        await user.should_not_see(marker="recurring-rule")
    assert list_rules(engine) == []


async def test_skipped_occurrences_are_restored_and_overdue_ones_skipped_in_the_rule_dialog(
    engine: Engine, account: int
) -> None:
    rule = add_rule(engine, _deposits(account))
    skip_occurrence(engine, rule.id, date(2026, 9, 10))
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-recurring-rule").click()
        with user.scope(marker="rule-skip"):
            await user.should_see("10.09.2026")
        user.find(marker="restore-skip").click()
        await user.should_not_see(marker="rule-skip")
        assert skipped_occurrences(engine, rule.id) == []

        # 10.09 and 12.10 are both before today
        user.find(marker="skip-overdue").click()
        await user.should_see("Pominięto 2 terminy.")
    assert skipped_occurrences(engine, rule.id) == [date(2026, 9, 10), date(2026, 10, 12)]


async def test_deposit_drafts_are_listed_counted_and_confirmed(engine: Engine, account: int) -> None:
    add_rule(engine, _deposits(account))
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        await user.should_see(marker="recurring-drafts")
        await user.should_see(marker="recurring-drafts-count", content="Cykliczne do zatwierdzenia: 2")
        await user.should_see("12.10.2026")

        _click_in_row(user, "confirm-recurring", "12.10.2026")

        await user.should_see(marker="recurring-drafts-count", content="Cykliczne do zatwierdzenia: 1")
        await user.should_see(marker="transaction-row")
    [saved] = list_transactions(engine)
    assert (saved.date, saved.actual_amount, saved.recurring_occurrence) == (
        date(2026, 10, 12),
        Decimal(1000),
        date(2026, 10, 12),
    )


async def test_a_draft_is_skipped(engine: Engine, account: int) -> None:
    rule = add_rule(engine, _deposits(account, start_date=date(2026, 10, 1)))
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="skip-recurring").click()
        await user.should_not_see(marker="recurring-drafts")
        await user.should_not_see(marker="recurring-drafts-count")
    assert skipped_occurrences(engine, rule.id) == [date(2026, 10, 12)]


async def test_a_deposit_draft_is_edited_in_the_transaction_dialog_before_its_saved(
    engine: Engine, account: int
) -> None:
    add_rule(engine, _deposits(account, start_date=date(2026, 10, 1)))
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="edit-recurring").click()
        await user.should_see(marker="transaction-amount")
        assert _value(user, "transaction-amount") == f"1{NBSP}000,00"
        _type(user, "transaction-amount", "900")
        user.find("Zapisz").click()
        await user.should_not_see(marker="recurring-drafts")
    [saved] = list_transactions(engine)
    assert (saved.actual_amount, saved.date, saved.recurring_occurrence) == (
        Decimal(900),
        date(2026, 10, 12),
        date(2026, 10, 12),
    )


async def test_a_buy_draft_opens_the_dialog_with_its_instrument_and_no_quantity_or_price(
    engine: Engine, account: int
) -> None:
    etf = _etf(engine)
    add_transaction(engine, deposit_or_withdrawal(account, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(5000)))
    buy = _deposits(
        account,
        name="Kupno ETF",
        transaction_type=TransactionType.BUY,
        instrument_id=etf,
        amount=Decimal(500),
        start_date=date(2026, 10, 1),
    )
    add_rule(engine, buy)
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        with user.scope(marker="recurring-draft"):
            await user.should_see("Kupno ETF")
            await user.should_see("ETF X")
            await user.should_see(f"ok. 500,00{NBSP}zł")
        await user.should_not_see(marker="confirm-recurring")
        user.find(marker="edit-recurring").click()
        await user.should_see(marker="transaction-quantity")
        assert _selected(user, "transaction-instrument") == etf
        assert _value(user, "transaction-quantity") == ""
        assert _value(user, "transaction-price") == ""
        _type(user, "transaction-quantity", "5")
        _type(user, "transaction-price", "99,5")
        user.find("Zapisz").click()
        await user.should_not_see(marker="recurring-drafts")
    bought = list_transactions(engine)[0]
    assert (bought.transaction_type, bought.date, bought.recurring_occurrence) == (
        TransactionType.BUY,
        date(2026, 10, 12),
        date(2026, 10, 12),
    )


async def test_a_buy_entered_by_hand_near_an_occurrence_leaves_no_draft(engine: Engine, account: int) -> None:
    etf = _etf(engine)
    add_transaction(engine, deposit_or_withdrawal(account, date(2026, 1, 2), TransactionType.DEPOSIT, Decimal(5000)))
    add_transaction(engine, buy_or_sell(account, date(2026, 10, 8), TransactionType.BUY, etf, Decimal(1), Decimal(9)))
    add_rule(
        engine,
        _deposits(account, transaction_type=TransactionType.BUY, instrument_id=etf, start_date=date(2026, 10, 1)),
    )
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        await user.should_see(marker="transaction-row")
        await user.should_not_see(marker="recurring-drafts")


async def test_repeat_opens_a_new_rule_filled_from_a_transaction(engine: Engine, account: int) -> None:
    add_transaction(engine, deposit_or_withdrawal(account, date(2026, 10, 5), TransactionType.DEPOSIT, Decimal(750)))
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/transakcje")
        user.find(marker="transaction-row").click()
        user.find(marker="repeat-transaction").click()
        await user.should_see(marker="rule-name")
        assert _value(user, "rule-amount") == "750,00"
        assert _value(user, "rule-day") == "5"
        # The next occurrence after the Transaction: 05.11.2026, a Thursday
        assert _value(user, "rule-start") == "05.11.2026"
        _type(user, "rule-name", "Wpłata IKE")
        user.find(marker="save-rule").click()
        # Closed, though the simulation keeps a closed dialog on the page
        [name] = user.find(marker="rule-name").elements
        assert not next(a for a in name.ancestors() if isinstance(a, ui.dialog)).value
    [rule] = list_rules(engine)
    assert (rule.amount, rule.day_of_month, rule.start_date) == (Decimal(750), 5, date(2026, 11, 5))
