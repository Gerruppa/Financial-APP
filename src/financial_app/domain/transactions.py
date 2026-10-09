"""Transactions and the Cash Balance they produce (spec 3.3, 3.5).

For now: PLN Deposits and Withdrawals, and Buys and Sells paid in PLN, also of foreign-currency Instruments.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from financial_app.domain.currencies import NbpRate

GROSZ = Decimal("0.01")


class TransactionError(ValueError):
    """A Transaction field the user must correct; the message is shown in the UI (Polish)."""


class TransactionType(StrEnum):
    """Values are stored in the database, so never rename them."""

    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    BUY = "buy"
    SELL = "sell"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def is_buy_or_sell(self) -> bool:
        """A Buy or Sell, which moves an Instrument as well as cash."""
        return self in (TransactionType.BUY, TransactionType.SELL)


_LABELS = {
    TransactionType.DEPOSIT: "Wpłata",
    TransactionType.WITHDRAWAL: "Wypłata",
    TransactionType.BUY: "Zakup",
    TransactionType.SELL: "Sprzedaż",
}


@dataclass(frozen=True)
class TransactionDraft:
    """The user-entered fields of a Transaction, validated on creation. ``actual_amount`` is positive PLN.

    A Buy or Sell also carries its Instrument, quantity, unit price (in the Instrument's currency) and PLN commission;
    build it with ``buy_or_sell``. One of a foreign-currency Instrument also carries the NBP Rate (D-1) for its Tax
    Amount and, if the user gave one, ``fx_rate``: the rate the Actual Amount was converted at.
    """

    account_id: int
    date: date
    transaction_type: TransactionType
    actual_amount: Decimal
    comment: str = ""
    instrument_id: int | None = field(default=None, kw_only=True)
    quantity: Decimal | None = field(default=None, kw_only=True)
    price: Decimal | None = field(default=None, kw_only=True)
    commission: Decimal = field(default=Decimal(0), kw_only=True)
    fx_rate: Decimal | None = field(default=None, kw_only=True)
    nbp_rate: NbpRate | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if not self.actual_amount > 0:
            raise TransactionError("Kwota musi być większa od zera.")
        if self.actual_amount != self.actual_amount.quantize(GROSZ):
            raise TransactionError("Kwotę podaj z dokładnością do grosza.")
        trade_fields = (self.instrument_id, self.quantity, self.price, self.fx_rate, self.nbp_rate)
        if self.transaction_type.is_buy_or_sell:
            if self.instrument_id is None:
                raise TransactionError("Wybierz instrument.")
            _check_buy_or_sell_fields(self.quantity, self.price, self.commission)
            _check_rates(self.fx_rate, self.nbp_rate)
        elif any(value is not None for value in trade_fields) or self.commission:
            raise TransactionError(f"{self.transaction_type.label} nie dotyczy instrumentu.")
        object.__setattr__(self, "comment", self.comment.strip())

    @property
    def tax_amount(self) -> Decimal:
        """The PLN amount at the NBP Rate, for tax reports; equal to the Actual Amount for PLN Transactions."""
        if self.nbp_rate is None:
            return self.actual_amount
        assert self.quantity is not None and self.price is not None  # a Buy or Sell, checked on creation
        return _with_commission(
            self.transaction_type, _pln(self.quantity * self.price * self.nbp_rate.rate), self.commission
        )

    @property
    def cash_change(self) -> Decimal:
        """How the Transaction moves the Account's PLN Cash Balance."""
        return self.actual_amount if self._is_incoming else -self.actual_amount

    @property
    def tax_cash_change(self) -> Decimal:
        """The Tax Amount with the sign of ``cash_change``."""
        return self.tax_amount if self._is_incoming else -self.tax_amount

    @property
    def _is_incoming(self) -> bool:
        return self.transaction_type in (TransactionType.DEPOSIT, TransactionType.SELL)


@dataclass(frozen=True)
class Transaction(TransactionDraft):
    """A saved Transaction."""

    id: int = field(kw_only=True)


def buy_or_sell(
    account_id: int,
    day: date,
    transaction_type: TransactionType,
    instrument_id: int,
    quantity: Decimal,
    price: Decimal,
    commission: Decimal = Decimal(0),
    comment: str = "",
    *,
    fx_rate: Decimal | None = None,
    nbp_rate: NbpRate | None = None,
) -> TransactionDraft:
    """A Buy or Sell paid in PLN: a Buy costs quantity × price × rate plus commission, a Sell brings that minus it.

    The rate is 1 for a PLN Instrument; for a foreign-currency one it is ``fx_rate`` if the user gave one, otherwise
    the NBP Rate, which ``nbp_rate`` must then carry.
    """
    _check_buy_or_sell_fields(quantity, price, commission)
    _check_rates(fx_rate, nbp_rate)
    rate = fx_rate or (nbp_rate.rate if nbp_rate else Decimal(1))
    value = _pln(quantity * price * rate)
    if value.is_zero():
        raise TransactionError("Wartość transakcji (liczba × cena) musi wynosić co najmniej 0,01 zł.")
    if transaction_type is TransactionType.SELL and commission >= value:
        raise TransactionError("Prowizja nie może przekraczać wartości sprzedaży.")
    actual_amount = _with_commission(transaction_type, value, commission)
    return TransactionDraft(
        account_id,
        day,
        transaction_type,
        actual_amount,
        comment,
        instrument_id=instrument_id,
        quantity=quantity,
        price=price,
        commission=commission,
        fx_rate=fx_rate,
        nbp_rate=nbp_rate,
    )


def _pln(value: Decimal) -> Decimal:
    return value.quantize(GROSZ, rounding=ROUND_HALF_UP)


def _with_commission(transaction_type: TransactionType, value: Decimal, commission: Decimal) -> Decimal:
    """A Buy costs its value plus commission; a Sell brings its value minus commission."""
    return value + commission if transaction_type is TransactionType.BUY else value - commission


def _check_rates(fx_rate: Decimal | None, nbp_rate: NbpRate | None) -> None:
    if fx_rate is not None and nbp_rate is None:
        raise TransactionError("Kurs podaje się tylko dla instrumentu w walucie obcej.")
    if fx_rate is not None and not fx_rate > 0:
        raise TransactionError("Kurs musi być większy od zera.")


def _check_buy_or_sell_fields(quantity: Decimal | None, price: Decimal | None, commission: Decimal) -> None:
    if quantity is None or not quantity > 0:
        raise TransactionError("Liczba musi być większa od zera.")
    if price is None or not price > 0:
        raise TransactionError("Cena musi być większa od zera.")
    if commission < 0:
        raise TransactionError("Prowizja nie może być ujemna.")
    if commission != commission.quantize(GROSZ):
        raise TransactionError("Prowizję podaj z dokładnością do grosza.")


def cash_balances(transactions: Iterable[TransactionDraft], on: date | None = None) -> dict[int, Decimal]:
    """PLN Cash Balance per Account id at the end of ``on`` (default: all Transactions).

    A balance may go negative: insufficient cash only warns (spec 3.3), so history can be entered in any order.
    """
    balances: dict[int, Decimal] = {}
    for transaction in transactions:
        if on is None or transaction.date <= on:
            balances[transaction.account_id] = (
                balances.get(transaction.account_id, Decimal(0)) + transaction.cash_change
            )
    return balances


def lowest_cash_balance(transactions: Iterable[TransactionDraft], account_id: int, start: date) -> Decimal:
    """The lowest end-of-day PLN Cash Balance of the Account from ``start`` on.

    Below zero means some Transaction lacks cash, which warns but does not block (spec 3.3).
    """
    own = [t for t in transactions if t.account_id == account_id]
    days = sorted({start} | {t.date for t in own if t.date >= start})
    return min(cash_balances(own, on=day).get(account_id, Decimal(0)) for day in days)
