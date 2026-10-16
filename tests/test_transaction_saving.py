"""Saving Transactions through one interface (#110), on in-memory SQLite: the save itself, the Bond Series it creates
or leaves, and what it warns of."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.transactions import TransactionDraft, TransactionError, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import migrate
from financial_app.persistence.instruments import add_instrument, list_asset_classes, list_instruments
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.sources.transaction_saving import checked_save, delete_saved, save_transaction

DAY = date(2026, 3, 2)


@pytest.fixture
def engine() -> Engine:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    migrate(engine)
    return engine


def _account(engine: Engine, account_type: AccountType = AccountType.REGULAR) -> int:
    return add_account(engine, AccountDraft("Konto", "Broker", account_type, ("PLN",))).id


def _deposit(account: int, amount: int, day: date = DAY) -> TransactionDraft:
    return TransactionDraft(account, day, TransactionType.DEPOSIT, Decimal(amount))


def _buy(account: int, instrument: int | None) -> TransactionDraft:
    assert instrument is not None
    return buy_or_sell(account, DAY, TransactionType.BUY, instrument, Decimal(1), Decimal(100))


def test_a_new_transaction_is_saved_and_a_withdrawal_beyond_the_cash_warns(engine: Engine) -> None:
    account = _account(engine)
    add_transaction(engine, _deposit(account, 100))
    withdrawal = TransactionDraft(account, DAY, TransactionType.WITHDRAWAL, Decimal(150))

    saved = save_transaction(engine, lambda _: withdrawal)

    assert saved.value == withdrawal
    assert len(list_transactions(engine)) == 2
    assert saved.warnings.messages("Zapisano") == ["Zapisano, ale Saldo gotówki konta Konto jest ujemne: -50,00\xa0zł."]


def test_an_edit_replaces_the_transaction_and_warns_of_the_limit_it_crosses(engine: Engine) -> None:
    account = _account(engine, AccountType.IKE)
    deposit = add_transaction(engine, _deposit(account, 28000))

    saved = save_transaction(engine, lambda _: _deposit(account, 29000), edited=deposit)

    assert [t.actual_amount for t in list_transactions(engine)] == [Decimal(29000)]
    assert saved.warnings.messages("Zapisano") == ["IKE 2026: przekroczono limit wpłat o 740,00\xa0zł."]


def test_a_bond_purchase_creates_its_series_and_a_failed_one_leaves_none(engine: Engine) -> None:
    account = _account(engine, AccountType.BONDS)
    add_transaction(engine, _deposit(account, 1000))

    saved = save_transaction(engine, lambda series: _buy(account, series), series="EDO0336")

    assert saved.warnings.series_created == ("EDO0336",)
    assert [i.name for i in list_instruments(engine)] == ["EDO0336"]

    def failing(_: int | None) -> TransactionDraft:
        raise TransactionError("Liczba musi być liczbą, np. 10 lub 0,5.")

    with pytest.raises(TransactionError):
        save_transaction(engine, failing, series="COI0330")
    assert [i.name for i in list_instruments(engine)] == ["EDO0336"]


def test_an_edited_bond_purchase_moving_to_another_series_drops_the_one_it_left(engine: Engine) -> None:
    account = _account(engine, AccountType.BONDS)
    add_transaction(engine, _deposit(account, 1000))
    save_transaction(engine, lambda series: _buy(account, series), series="EDO0336")
    bought = next(t for t in list_transactions(engine) if t.transaction_type is TransactionType.BUY)

    saved = save_transaction(engine, lambda series: _buy(account, series), edited=bought, series="EDO0436")

    assert (saved.warnings.series_created, saved.warnings.series_dropped) == (("EDO0436",), ("EDO0336",))


def test_an_automatic_exchange_is_saved_before_the_buy(engine: Engine) -> None:
    account = add_account(engine, AccountDraft("Konto", "Broker", AccountType.REGULAR, ("PLN", "USD"))).id
    asset_class = list_asset_classes(engine)[0].id
    apple = add_instrument(engine, InstrumentDraft("Apple", asset_class, "USD")).id
    add_transaction(engine, _deposit(account, 1000))
    rate = NbpRate("USD", Decimal(4), date(2026, 2, 27), "test")
    buy = buy_or_sell(
        account, DAY, TransactionType.BUY, apple, Decimal(1), Decimal(100), nbp_rate=rate, cash_currency="USD"
    )

    saved = save_transaction(engine, lambda _: buy, with_exchange=True)

    kinds = [t.transaction_type for t in list_transactions(engine)]
    assert kinds.count(TransactionType.CURRENCY_EXCHANGE) == 1
    assert saved.warnings.messages("Zapisano") == []


def test_deleting_the_deposit_a_withdrawal_spends_warns(engine: Engine) -> None:
    account = _account(engine)
    deposit = add_transaction(engine, _deposit(account, 100))
    add_transaction(engine, TransactionDraft(account, DAY, TransactionType.WITHDRAWAL, Decimal(100)))

    deleted = delete_saved(engine, deposit.id)

    assert deleted.warnings.messages("Usunięto") == [
        "Usunięto, ale Saldo gotówki konta Konto jest ujemne: -100,00\xa0zł."
    ]


def test_any_other_save_goes_through_the_same_check(engine: Engine) -> None:
    account = _account(engine, AccountType.IKE)

    saved = checked_save(engine, lambda: add_transaction(engine, _deposit(account, 30000)).id)

    assert saved.value == list_transactions(engine)[0].id
    assert saved.warnings.messages("Zapisano") == ["IKE 2026: przekroczono limit wpłat o 1\xa0740,00\xa0zł."]
