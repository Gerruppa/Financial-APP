"""Deposits, Withdrawals and the PLN Cash Balance of each Account (issue #11, spec 3.5)."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.currencies import NbpRate
from financial_app.domain.transactions import (
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    cash_balances,
    lowest_cash_balance,
)

IKE, XTB = 1, 2


def _deposit(account_id: int, amount: str, day: int = 1) -> TransactionDraft:
    return TransactionDraft(account_id, date(2026, 1, day), TransactionType.DEPOSIT, Decimal(amount))


def _withdrawal(account_id: int, amount: str, day: int = 1) -> TransactionDraft:
    return TransactionDraft(account_id, date(2026, 1, day), TransactionType.WITHDRAWAL, Decimal(amount))


def test_account_without_transactions_has_no_balance_entry() -> None:
    assert cash_balances([]) == {}


def test_deposit_increases_the_cash_balance() -> None:
    assert cash_balances([_deposit(IKE, "1000"), _deposit(IKE, "250.50")]) == {IKE: Decimal("1250.50")}


def test_withdrawal_decreases_the_cash_balance() -> None:
    assert cash_balances([_deposit(IKE, "1000"), _withdrawal(IKE, "300")]) == {IKE: Decimal("700")}


def test_balances_are_kept_per_account() -> None:
    balances = cash_balances([_deposit(IKE, "1000"), _deposit(XTB, "500"), _withdrawal(XTB, "200")])

    assert balances == {IKE: Decimal("1000"), XTB: Decimal("300")}


def test_withdrawal_beyond_the_balance_is_allowed_and_goes_negative() -> None:
    # Insufficient cash only warns (spec 3.3), so history can be entered in any order
    assert cash_balances([_withdrawal(IKE, "100")]) == {IKE: Decimal("-100")}


def test_balance_on_a_date_ignores_later_transactions() -> None:
    transactions = [_deposit(IKE, "1000", day=1), _withdrawal(IKE, "400", day=10)]

    assert cash_balances(transactions, on=date(2026, 1, 9)) == {IKE: Decimal("1000")}
    assert cash_balances(transactions, on=date(2026, 1, 10)) == {IKE: Decimal("600")}


def test_transaction_types_have_polish_labels() -> None:
    assert [t.label for t in TransactionType] == [
        "Wpłata",
        "Wypłata",
        "Zakup",
        "Sprzedaż",
        "Dywidenda / odsetki",
        "Koszty",
        "Wymiana walut",
        "DRIP",
        "Split",
        "Transfer gotówki",
        "Transfer papierów",
    ]


@pytest.mark.parametrize("amount", ["0", "-5"])
def test_amount_must_be_positive(amount: str) -> None:
    with pytest.raises(TransactionError, match="większa od zera"):
        _deposit(IKE, amount)


def test_amount_is_kept_to_the_grosz() -> None:
    with pytest.raises(TransactionError, match="grosza"):
        _deposit(IKE, "10.005")


def test_comment_is_trimmed() -> None:
    draft = TransactionDraft(IKE, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(1), comment="  premia ")

    assert draft.comment == "premia"


def test_lowest_cash_balance_from_a_date_finds_a_later_dip() -> None:
    transactions = [_deposit(IKE, "1000", day=1), _withdrawal(IKE, "900", day=10), _deposit(IKE, "500", day=20)]

    assert lowest_cash_balance(transactions, IKE, start=date(2026, 1, 5)) == Decimal("100")


def test_backdated_withdrawal_that_breaks_a_later_balance_is_found() -> None:
    transactions = [_deposit(IKE, "100", day=1), _withdrawal(IKE, "80", day=10), _withdrawal(IKE, "50", day=5)]

    assert lowest_cash_balance(transactions, IKE, start=date(2026, 1, 5)) == Decimal("-30")


def test_lowest_cash_balance_ignores_other_accounts() -> None:
    transactions = [_deposit(IKE, "100"), _withdrawal(XTB, "500")]

    assert lowest_cash_balance(transactions, IKE, start=date(2026, 1, 1)) == Decimal("100")


def _trade(kind: TransactionType, quantity: str = "10", price: str = "25.5", fee: str = "3") -> TransactionDraft:
    return buy_or_sell(IKE, date(2026, 1, 1), kind, 7, Decimal(quantity), Decimal(price), Decimal(fee))


def test_buy_costs_its_value_plus_the_commission() -> None:
    buy = _trade(TransactionType.BUY)

    assert (buy.instrument_id, buy.quantity, buy.price, buy.commission) == (7, Decimal(10), Decimal("25.5"), Decimal(3))
    assert buy.actual_amount == Decimal("258.00")
    assert buy.cash_change == Decimal("-258.00")


def test_sell_brings_its_value_minus_the_commission() -> None:
    sell = _trade(TransactionType.SELL)

    assert sell.actual_amount == Decimal("252.00")
    assert sell.cash_change == Decimal("252.00")


def test_trade_value_is_rounded_to_the_grosz() -> None:
    assert _trade(TransactionType.BUY, quantity="3", price="0.333", fee="0").actual_amount == Decimal("1.00")


def test_trades_move_the_cash_balance() -> None:
    transactions = [_deposit(IKE, "1000"), _trade(TransactionType.BUY), _trade(TransactionType.SELL, quantity="5")]

    assert cash_balances(transactions) == {IKE: Decimal("1000") - Decimal("258") + Decimal("124.50")}


@pytest.mark.parametrize(
    ("quantity", "price", "fee", "message"),
    [
        ("0", "10", "0", "Liczba musi być większa od zera"),
        ("1", "0", "0", "Cena musi być większa od zera"),
        ("1", "10", "-1", "Prowizja nie może być ujemna"),
        ("1", "10", "0.001", "Prowizję podaj z dokładnością do grosza"),
    ],
)
def test_trade_fields_are_validated(quantity: str, price: str, fee: str, message: str) -> None:
    with pytest.raises(TransactionError, match=message):
        _trade(TransactionType.BUY, quantity, price, fee)


def test_sell_commission_cannot_exceed_its_value() -> None:
    with pytest.raises(TransactionError, match="Prowizja nie może przekraczać"):
        _trade(TransactionType.SELL, quantity="1", price="2", fee="2")


def test_cash_transactions_carry_no_instrument() -> None:
    with pytest.raises(TransactionError):
        TransactionDraft(IKE, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(1), instrument_id=7)


def test_trade_needs_an_instrument() -> None:
    with pytest.raises(TransactionError, match="instrument"):
        TransactionDraft(IKE, date(2026, 1, 1), TransactionType.BUY, Decimal(1))


def test_trade_worth_less_than_a_grosz_is_rejected() -> None:
    with pytest.raises(TransactionError, match="co najmniej 0,01"):
        _trade(TransactionType.BUY, quantity="0.001", price="0.01", fee="0")


# Foreign-currency Buys and Sells on a PLN Account (issue #15, spec 3.3)
APPLE = 7
USD_RATE = NbpRate("USD", Decimal("3.6045"), date(2026, 1, 5), "002/A/NBP/2026")


def _foreign(kind: TransactionType, fx_rate: str | None = None, fee: str = "5") -> TransactionDraft:
    return buy_or_sell(
        IKE,
        date(2026, 1, 7),
        kind,
        APPLE,
        Decimal(10),
        Decimal("150.5"),
        Decimal(fee),
        fx_rate=None if fx_rate is None else Decimal(fx_rate),
        nbp_rate=USD_RATE,
    )


def test_foreign_buy_without_a_rate_of_its_own_costs_the_nbp_rate() -> None:
    buy = _foreign(TransactionType.BUY)

    # 10 × 150,50 USD × 3,6045 = 5424,77 zł, plus 5 zł commission
    assert buy.actual_amount == Decimal("5429.77")
    assert buy.tax_amount == Decimal("5429.77")


def test_foreign_buy_at_the_users_rate_keeps_the_tax_amount_at_the_nbp_rate() -> None:
    buy = _foreign(TransactionType.BUY, fx_rate="3.65")

    assert buy.actual_amount == Decimal("5498.25")  # 5493,25 + 5
    assert buy.tax_amount == Decimal("5429.77")


def test_foreign_sell_brings_its_value_minus_the_commission_at_both_rates() -> None:
    sell = _foreign(TransactionType.SELL, fx_rate="3.55")

    assert sell.actual_amount == Decimal("5337.75")  # 5342,75 - 5
    assert sell.tax_amount == Decimal("5419.77")


def test_pln_transactions_have_a_tax_amount_equal_to_the_actual_amount() -> None:
    assert _deposit(IKE, "100").tax_amount == Decimal(100)
    pln_buy = buy_or_sell(IKE, date(2026, 1, 1), TransactionType.BUY, APPLE, Decimal(2), Decimal(10), Decimal(1))
    assert pln_buy.tax_amount == pln_buy.actual_amount == Decimal(21)


def test_own_rate_needs_an_nbp_rate_too() -> None:
    with pytest.raises(TransactionError, match="walucie obcej"):
        buy_or_sell(IKE, date(2026, 1, 1), TransactionType.BUY, APPLE, Decimal(1), Decimal(1), fx_rate=Decimal("3.6"))


@pytest.mark.parametrize("fx_rate", ["0", "-1"])
def test_own_rate_must_be_positive(fx_rate: str) -> None:
    with pytest.raises(TransactionError, match="Kurs musi być większy od zera"):
        _foreign(TransactionType.BUY, fx_rate=fx_rate)


def test_cash_transactions_carry_no_nbp_rate() -> None:
    with pytest.raises(TransactionError, match="nie dotyczy instrumentu"):
        TransactionDraft(IKE, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(1), nbp_rate=USD_RATE)
