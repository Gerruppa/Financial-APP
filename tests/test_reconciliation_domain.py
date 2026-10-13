"""Pairing a broker's Transactions with the entered ones (Reconciliation, L-17, spec 7)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from financial_app.domain.reconciliation import Pair, item_key, reconcile
from financial_app.domain.transactions import (
    Origin,
    Transaction,
    TransactionDraft,
    TransactionType,
    buy_or_sell,
    cash_transfer,
)

IKE = 2


def deposit(day: date, amount: str, account: int = IKE) -> TransactionDraft:
    return TransactionDraft(account, day, TransactionType.DEPOSIT, Decimal(amount))


def withdrawal(day: date, amount: str) -> TransactionDraft:
    return TransactionDraft(IKE, day, TransactionType.WITHDRAWAL, Decimal(amount))


def buy(day: date, quantity: str, amount: str, instrument: int = 7) -> TransactionDraft:
    draft = buy_or_sell(IKE, day, TransactionType.BUY, instrument, Decimal(quantity), Decimal(1))
    return replace(draft, actual_amount=Decimal(amount))


def broker(draft: TransactionDraft, id: str) -> TransactionDraft:
    return replace(draft, origin=Origin.BROKER, external_id=f"xtb-{id}")


def mine(draft: TransactionDraft, id: int) -> Transaction:
    return Transaction(**{**draft.__dict__, "id": id})


def test_a_buy_pairs_by_quantity_within_three_days_even_with_another_amount() -> None:
    entered = mine(buy(date(2026, 7, 30), "15.3224", "6940.67"), 1)
    xtb = broker(buy(date(2026, 7, 30), "15.3224", "6861.82"), "1")
    result = reconcile([xtb], [entered])
    assert result.pairs == [Pair(entered, xtb)]
    assert not result.pairs[0].same
    assert result.different == result.pairs


def test_the_same_pair_agrees_on_date_and_amount() -> None:
    entered = mine(buy(date(2026, 4, 24), "0.3479", "145.69"), 1)
    xtb = broker(buy(date(2026, 4, 24), "0.3479", "145.68"), "1")
    assert reconcile([xtb], [entered]).same == [Pair(entered, xtb)]


def test_a_buy_four_days_apart_or_of_another_quantity_does_not_pair() -> None:
    entered = [mine(buy(date(2026, 7, 26), "1", "100"), 1), mine(buy(date(2026, 7, 30), "2", "200"), 2)]
    xtb = broker(buy(date(2026, 7, 30), "1", "100"), "1")
    result = reconcile([xtb], entered)
    assert result.pairs == []
    assert result.broker_only == [xtb]
    assert result.mine_only == entered


def test_deposits_pair_only_with_about_the_same_amount() -> None:
    entered = [mine(deposit(date(2026, 7, 30), "7100"), 1), mine(deposit(date(2026, 6, 11), "1000.06"), 2)]
    xtb = [
        broker(deposit(date(2026, 7, 30), "6000"), "1"),
        broker(deposit(date(2026, 7, 30), "100"), "2"),
        broker(deposit(date(2026, 6, 11), "1000.06"), "3"),
    ]
    result = reconcile(xtb, entered)
    assert [pair.mine.id for pair in result.pairs] == [2]
    assert [draft.external_id for draft in result.broker_only] == ["xtb-1", "xtb-2"]
    assert [t.id for t in result.mine_only] == [1]


def test_the_closest_date_pairs_first() -> None:
    entered = [mine(buy(date(2026, 7, 12), "1", "100"), 1), mine(buy(date(2026, 7, 14), "1", "100"), 2)]
    xtb = broker(buy(date(2026, 7, 14), "1", "100"), "1")
    assert reconcile([xtb], entered).pairs[0].mine.id == 2


def test_items_are_keyed_for_their_choice() -> None:
    entered = mine(deposit(date(2026, 1, 2), "1"), 5)
    xtb = broker(deposit(date(2026, 1, 2), "1"), "9")
    assert item_key(Pair(entered, xtb)) == "xtb-9"
    assert item_key(xtb) == "xtb-9"
    assert item_key(entered) == "mine-5"


def test_a_pair_differing_only_in_price_is_not_the_same() -> None:
    entered = mine(buy(date(2026, 4, 22), "0.2961", "146.98"), 1)
    xtb = broker(replace(buy(date(2026, 4, 22), "0.2961", "146.98"), price=Decimal("1.5")), "1")
    assert reconcile([xtb], [entered]).different == [Pair(entered, xtb)]


def test_an_entered_transfer_pairs_with_the_brokers_deposit_or_withdrawal_and_stays() -> None:
    bank = 9
    into = mine(cash_transfer(bank, date(2026, 7, 24), IKE, Decimal(1000)), 1)
    out = mine(cash_transfer(IKE, date(2026, 8, 1), bank, Decimal(200)), 2)
    xtb = [broker(deposit(date(2026, 7, 24), "1000"), "1"), broker(withdrawal(date(2026, 8, 1), "200"), "2")]
    result = reconcile(xtb, [out], incoming=[into])
    assert [(pair.mine.id, pair.linked, pair.same) for pair in result.pairs] == [(1, True, True), (2, True, True)]
    assert reconcile([], [out], incoming=[into]).mine_only == [out]
