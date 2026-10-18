"""Saving Recurring Rules and their skips, and confirming their Drafts (issue #97)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import InstrumentDraft, InstrumentError
from financial_app.domain.recurring import Frequency, RecurringRuleDraft, RecurringRuleError
from financial_app.domain.transactions import TransactionType, buy_or_sell, deposit_or_withdrawal
from financial_app.persistence.accounts import add_account, delete_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, delete_instrument, list_asset_classes
from financial_app.persistence.recurring_rules import (
    add_rule,
    confirm_recurring_draft,
    delete_rule,
    list_rules,
    pending_recurring_drafts,
    restore_occurrence,
    set_rule_active,
    skip_occurrence,
    skip_overdue,
    skipped_occurrences,
    update_rule,
)
from financial_app.persistence.reset import clear_portfolio
from financial_app.persistence.transactions import add_transaction, list_transactions

TODAY = date(2026, 4, 15)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def account(engine: Engine) -> int:
    return add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN", "USD"))).id


def monthly(account_id: int, **fields: object) -> RecurringRuleDraft:
    values: dict[str, object] = {
        "name": "Wpłata IKE",
        "account_id": account_id,
        "transaction_type": TransactionType.DEPOSIT,
        "amount": Decimal("1000.50"),
        "currency": "PLN",
        "frequency": Frequency.MONTHLY,
        "day_of_month": 10,
        "start_date": date(2026, 3, 1),
    }
    values.update(fields)
    return RecurringRuleDraft(**values)  # type: ignore[arg-type]


def test_rules_are_added_edited_switched_off_and_deleted(engine: Engine, account: int) -> None:
    rule = add_rule(engine, monthly(account))
    assert list_rules(engine) == [rule]
    assert rule.amount == Decimal("1000.50")

    edited = update_rule(engine, rule.id, monthly(account, name="IKE co kwartał", frequency=Frequency.QUARTERLY))
    assert list_rules(engine) == [edited]
    assert edited.frequency is Frequency.QUARTERLY

    set_rule_active(engine, rule.id, False)
    assert not list_rules(engine)[0].active

    delete_rule(engine, rule.id)
    assert list_rules(engine) == []


def test_a_rule_takes_one_of_its_accounts_cash_currencies_and_an_existing_instrument(
    engine: Engine, account: int
) -> None:
    with pytest.raises(RecurringRuleError, match="nie ma waluty rachunku EUR"):
        add_rule(engine, monthly(account, currency="EUR"))
    with pytest.raises(RecurringRuleError, match="instrument nie istnieje"):
        add_rule(engine, monthly(account, transaction_type=TransactionType.BUY, instrument_id=99))
    with pytest.raises(RecurringRuleError, match="konto nie istnieje"):
        add_rule(engine, monthly(99))


def test_drafts_are_confirmed_with_their_link_and_skipped_or_restored(engine: Engine, account: int) -> None:
    rule = add_rule(engine, monthly(account))
    march, april = pending_recurring_drafts(engine, TODAY)
    assert (march.due, april.due) == (date(2026, 3, 10), date(2026, 4, 10))

    saved = confirm_recurring_draft(engine, march, rates=_no_rates)
    assert (saved.recurring_rule_id, saved.recurring_occurrence) == (rule.id, date(2026, 3, 10))
    assert saved.actual_amount == Decimal("1000.50")

    skip_occurrence(engine, rule.id, april.due)
    assert pending_recurring_drafts(engine, TODAY) == []
    assert skipped_occurrences(engine, rule.id) == [april.due]

    restore_occurrence(engine, rule.id, april.due)
    assert [d.due for d in pending_recurring_drafts(engine, TODAY)] == [april.due]


def test_a_foreign_deposit_is_confirmed_at_the_nbp_rate(engine: Engine, account: int) -> None:
    add_rule(engine, monthly(account, currency="USD", amount=Decimal(100)))
    rate = NbpRate("USD", Decimal("3.6000"), date(2026, 3, 9), "045/A/NBP/2026")
    first = pending_recurring_drafts(engine, TODAY)[0]

    saved = confirm_recurring_draft(engine, first, rates=lambda currency, day: rate)

    assert (saved.quantity, saved.actual_amount, saved.cash_currency) == (Decimal(100), Decimal("360.00"), "USD")


def test_skipping_overdue_occurrences_skips_the_uncovered_ones_before_today(engine: Engine, account: int) -> None:
    rule = add_rule(engine, monthly(account, start_date=date(2026, 1, 1)))
    add_transaction(engine, deposit_or_withdrawal(account, date(2026, 2, 12), TransactionType.DEPOSIT, Decimal(5)))

    assert skip_overdue(engine, rule.id, date(2026, 4, 10)) == 2

    # 12.01 and 10.03 skipped, 10.02 covered by the Deposit, 10.04 (today) left
    assert skipped_occurrences(engine, rule.id) == [date(2026, 1, 12), date(2026, 3, 10)]
    assert [d.due for d in pending_recurring_drafts(engine, date(2026, 4, 10))] == [date(2026, 4, 10)]


def test_deleting_a_rule_keeps_its_transactions_unlinked(engine: Engine, account: int) -> None:
    rule = add_rule(engine, monthly(account))
    confirm_recurring_draft(engine, pending_recurring_drafts(engine, TODAY)[0], rates=_no_rates)
    skip_occurrence(engine, rule.id, date(2026, 4, 10))

    delete_rule(engine, rule.id)

    [kept] = list_transactions(engine)
    assert (kept.recurring_rule_id, kept.recurring_occurrence) == (None, None)
    again = add_rule(engine, monthly(account))
    assert skipped_occurrences(engine, again.id) == []


def test_a_deleted_account_takes_its_rules_and_skips(engine: Engine, account: int) -> None:
    rule = add_rule(engine, monthly(account))
    skip_occurrence(engine, rule.id, date(2026, 3, 10))

    delete_account(engine, account)

    assert list_rules(engine) == []
    assert skipped_occurrences(engine, rule.id) == []


def test_clearing_the_data_removes_rules_and_skips(engine: Engine, account: int, tmp_path: Path) -> None:
    rule = add_rule(engine, monthly(account))
    skip_occurrence(engine, rule.id, date(2026, 3, 10))

    clear_portfolio(engine)

    assert list_rules(engine) == []
    assert skipped_occurrences(engine, rule.id) == []


def test_an_instrument_a_rule_buys_is_not_deleted(engine: Engine, account: int) -> None:
    asset_class = list_asset_classes(engine)[0]
    etf = add_instrument(engine, InstrumentDraft("ETF X", asset_class.id, "PLN", "GPW"))
    add_rule(engine, monthly(account, transaction_type=TransactionType.BUY, instrument_id=etf.id))

    with pytest.raises(InstrumentError, match="reguła cykliczna"):
        delete_instrument(engine, etf.id)


@pytest.fixture
def broker(engine: Engine) -> int:
    return add_account(engine, AccountDraft("Konto maklerskie", "mBank", AccountType.REGULAR, ("PLN",))).id


def test_a_cash_transfer_rule_names_an_existing_target_holding_its_currency(
    engine: Engine, account: int, broker: int
) -> None:
    transfer = {"transaction_type": TransactionType.CASH_TRANSFER, "target_account_id": broker}
    rule = add_rule(engine, monthly(account, **transfer))
    assert list_rules(engine)[0].target_account_id == broker
    with pytest.raises(RecurringRuleError, match="Konto maklerskie nie ma waluty rachunku USD"):
        update_rule(engine, rule.id, monthly(account, currency="USD", **transfer))
    with pytest.raises(RecurringRuleError, match="konto docelowe nie istnieje"):
        add_rule(engine, monthly(account, transaction_type=TransactionType.CASH_TRANSFER, target_account_id=99))


def test_only_a_cash_transfer_rule_keeps_a_target_account(engine: Engine, account: int, broker: int) -> None:
    rule = add_rule(engine, monthly(account, transaction_type=TransactionType.CASH_TRANSFER, target_account_id=broker))
    deposit = update_rule(engine, rule.id, monthly(account, target_account_id=broker))
    assert deposit.target_account_id is None


def test_cost_and_cash_transfer_drafts_are_confirmed_as_they_stand(engine: Engine, account: int, broker: int) -> None:
    add_rule(engine, monthly(account, name="Opłata", transaction_type=TransactionType.COST, amount=Decimal(5)))
    add_rule(
        engine,
        monthly(account, name="Na konto", transaction_type=TransactionType.CASH_TRANSFER, target_account_id=broker),
    )
    fee, moved = pending_recurring_drafts(engine, date(2026, 3, 10))

    saved_fee = confirm_recurring_draft(engine, fee, rates=_no_rates)
    saved_move = confirm_recurring_draft(engine, moved, rates=_no_rates)

    assert (saved_fee.transaction_type, saved_fee.actual_amount) == (TransactionType.COST, Decimal(5))
    assert (saved_move.transaction_type, saved_move.target_account_id) == (TransactionType.CASH_TRANSFER, broker)
    assert pending_recurring_drafts(engine, date(2026, 3, 10)) == []


def test_a_cash_transfer_rules_draft_shows_in_its_targets_view(engine: Engine, account: int, broker: int) -> None:
    add_rule(engine, monthly(account, transaction_type=TransactionType.CASH_TRANSFER, target_account_id=broker))
    assert [d.due for d in pending_recurring_drafts(engine, date(2026, 3, 10), broker)] == [date(2026, 3, 10)]


def test_a_deleted_target_account_takes_its_cash_transfer_rules(engine: Engine, account: int, broker: int) -> None:
    add_rule(engine, monthly(account, transaction_type=TransactionType.CASH_TRANSFER, target_account_id=broker))
    add_rule(engine, monthly(account))

    delete_account(engine, broker)

    assert [rule.transaction_type for rule in list_rules(engine)] == [TransactionType.DEPOSIT]


def test_a_bond_buy_rule_is_covered_by_the_next_months_series(engine: Engine, account: int) -> None:
    treasury = next(c for c in list_asset_classes(engine) if c.name == "Obligacje skarbowe polskie")
    march = add_instrument(engine, InstrumentDraft("EDO0336", treasury.id, "PLN")).id
    april = add_instrument(engine, InstrumentDraft("EDO0436", treasury.id, "PLN")).id
    add_rule(engine, monthly(account, transaction_type=TransactionType.BUY, instrument_id=march))
    add_transaction(
        engine, buy_or_sell(account, date(2026, 4, 9), TransactionType.BUY, april, Decimal(10), Decimal(100))
    )

    assert [d.due for d in pending_recurring_drafts(engine, TODAY)] == [date(2026, 3, 10)]


def _no_rates(currency: str, day: date) -> NbpRate:
    raise AssertionError("a PLN Deposit needs no NBP Rate")
