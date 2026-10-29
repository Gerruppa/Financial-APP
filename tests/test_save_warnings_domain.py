"""What a save warns of (#110): computed from the Transactions before and after it, whichever place saved."""

from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.instruments import Instrument, InstrumentType
from financial_app.domain.save_warnings import CashShortfall, save_warnings, touched
from financial_app.domain.transactions import Transaction, TransactionType, security_transfer

IKE, REGULAR = 1, 2
ACCOUNTS = [
    Account("mBank IKE", "mBank", AccountType.IKE, ("PLN", "USD"), id=IKE),
    Account("XTB", "XTB", AccountType.REGULAR, ("PLN",), id=REGULAR),
]
LIMITS = {2026: {AccountType.IKE: Decimal(1000)}}


def _saved(transaction_id: int, account_id: int, kind: TransactionType, amount: int, day: int = 1) -> Transaction:
    return Transaction(account_id, date(2026, 3, day), kind, Decimal(amount), id=transaction_id)


def _instrument(instrument_id: int, name: str, multi_asset: bool = False, bond_class: bool = False) -> Instrument:
    return Instrument(
        name,
        1,
        "PLN",
        id=instrument_id,
        asset_class_name="Obligacje skarbowe polskie" if bond_class else "Multi-asset",
        fallback_order=(),
        in_multi_asset_class=multi_asset,
    )


def test_touched_gives_the_added_the_removed_and_both_forms_of_a_changed_transaction() -> None:
    kept = _saved(1, IKE, TransactionType.DEPOSIT, 100)
    old = _saved(2, IKE, TransactionType.DEPOSIT, 100)
    new = _saved(2, IKE, TransactionType.DEPOSIT, 200)
    gone = _saved(3, IKE, TransactionType.DEPOSIT, 100)
    added = _saved(4, IKE, TransactionType.DEPOSIT, 100)

    assert touched([kept, old, gone], [kept, new, added]) == [new, added, old, gone]


def test_a_save_of_nothing_warns_of_nothing() -> None:
    deposit = _saved(1, IKE, TransactionType.DEPOSIT, 100)

    warnings = save_warnings([deposit], [deposit], ACCOUNTS, [], [], LIMITS)

    assert not warnings.any


def test_a_deposit_over_the_limit_warns_with_the_bar() -> None:
    before = [_saved(1, IKE, TransactionType.DEPOSIT, 900)]
    after = [*before, _saved(2, IKE, TransactionType.DEPOSIT, 300)]

    warnings = save_warnings(before, after, ACCOUNTS, [], [], LIMITS)

    assert [(bar.account_type, bar.over) for bar in warnings.over_limit] == [(AccountType.IKE, Decimal(200))]
    assert warnings.messages("Zapisano") == ["IKE 2026: przekroczono limit wpłat o 200,00\xa0zł."]


def test_a_withdrawal_leaving_cash_negative_warns_per_account_and_currency_from_its_day() -> None:
    before = [_saved(1, REGULAR, TransactionType.DEPOSIT, 100)]
    after = [*before, _saved(2, REGULAR, TransactionType.WITHDRAWAL, 150, day=5)]

    warnings = save_warnings(before, after, ACCOUNTS, [], [], LIMITS)

    assert warnings.negative_cash == (CashShortfall("XTB", "PLN", Decimal(-50), REGULAR),)
    assert warnings.messages("Zapisano") == ["Zapisano, ale Saldo gotówki konta XTB jest ujemne: -50,00\xa0zł."]
    # The fix the warning offers: the Account's covering Deposits (#267)
    assert warnings.short_of_pln == (REGULAR,)


def test_deleting_the_deposit_a_withdrawal_spends_warns_too() -> None:
    deposit = _saved(1, REGULAR, TransactionType.DEPOSIT, 100)
    withdrawal = _saved(2, REGULAR, TransactionType.WITHDRAWAL, 100, day=5)

    warnings = save_warnings([deposit, withdrawal], [withdrawal], ACCOUNTS, [], [], LIMITS)

    assert warnings.messages("Usunięto") == ["Usunięto, ale Saldo gotówki konta XTB jest ujemne: -100,00\xa0zł."]


def test_a_buy_of_a_multi_asset_instrument_without_a_split_names_it() -> None:
    fund = _instrument(7, "V80A", multi_asset=True)
    deposit = _saved(1, REGULAR, TransactionType.DEPOSIT, 1000)
    buy = Transaction(
        REGULAR, date(2026, 3, 2), TransactionType.BUY, Decimal(100),
        instrument_id=7, quantity=Decimal(1), price=Decimal(100), id=2,
    )  # fmt: skip

    warnings = save_warnings([deposit], [deposit, buy], ACCOUNTS, [fund], [fund], LIMITS)

    assert warnings.unsplit == (fund,)
    assert warnings.messages("Zapisano") == [
        "Instrumenty Multi-asset bez podziału na klasy: V80A. Podaj go w zakładce Multi-asset."
    ]
    assert warnings.messages("Zapisano", unsplit=False) == []


def _bond_buy(transaction_id: int, account_id: int) -> Transaction:
    return Transaction(
        account_id, date(2026, 3, 2), TransactionType.BUY, Decimal(100),
        instrument_id=3, quantity=Decimal(1), price=Decimal(100), id=transaction_id,
    )  # fmt: skip


def test_a_bond_series_bought_on_a_regular_account_warns_with_what_the_account_may_buy() -> None:
    series = _instrument(3, "EDO0336", bond_class=True)

    deposit = _saved(9, REGULAR, TransactionType.DEPOSIT, 1000, day=1)

    warnings = save_warnings([deposit], [deposit, _bond_buy(1, REGULAR)], ACCOUNTS, [series], [series], LIMITS)

    assert warnings.any
    assert warnings.messages("Zapisano") == [
        "Konto XTB typu Regular nie przyjmuje obligacji skarbowych detalicznych (EDO0336). "
        "Załóż do nich konto typu Obligacje lub kup je na koncie IKE albo IKZE. "
        "Na tym koncie można kupić: akcje, ETF, ETC i obligacje giełdowe, fundusze, kryptowaluty, "
        "instrumenty typu Inne."
    ]


def test_a_buy_the_account_may_make_or_a_deleted_one_warns_of_nothing() -> None:
    series = _instrument(3, "EDO0336", bond_class=True)
    accounts = [*ACCOUNTS, Account("PKO obligacje", "PKO", AccountType.BONDS, ("PLN",), id=3)]
    bought = [_bond_buy(1, 3), _bond_buy(2, IKE)]

    assert save_warnings([], bought, accounts, [series], [series], LIMITS).not_allowed == ()
    assert save_warnings([_bond_buy(4, REGULAR)], [], accounts, [series], [series], LIMITS).not_allowed == ()


def test_a_security_transferred_to_an_account_that_may_not_hold_it_warns_of_the_target() -> None:
    etf = Instrument(
        "VWCE", 1, "PLN", instrument_type=InstrumentType.ETF, id=5, asset_class_name="Akcje zagraniczne",
        fallback_order=(),
    )  # fmt: skip
    bonds = Account("PKO obligacje", "PKO", AccountType.BONDS, ("PLN",), id=3)
    transfer = security_transfer(REGULAR, date(2026, 3, 2), 3, 5, Decimal(1)).with_id(1)

    warnings = save_warnings([], [transfer], [*ACCOUNTS, bonds], [etf], [etf], LIMITS)

    assert [w.account_name for w in warnings.not_allowed] == ["PKO obligacje"]


def test_bond_series_created_or_removed_by_the_save_are_named() -> None:
    kept = _instrument(1, "EDO0136", bond_class=True)
    old = _instrument(2, "EDO0236", bond_class=True)
    new = _instrument(3, "EDO0336", bond_class=True)

    warnings = save_warnings([], [], ACCOUNTS, [kept, old], [kept, new], LIMITS)

    assert (warnings.series_created, warnings.series_dropped) == (("EDO0336",), ("EDO0236",))
    assert warnings.messages("Zapisano") == []
