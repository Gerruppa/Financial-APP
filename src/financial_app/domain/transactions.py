"""Transactions and the Cash Balances they produce (spec 3.3, 3.5).

For now: PLN Deposits and Withdrawals, Buys and Sells (paid in PLN, optionally converted by the broker for an FX
Conversion Fee, or, on an Account holding the Instrument's currency, from that foreign cash) and Currency Exchanges
between PLN and a foreign Cash Currency.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from financial_app.domain.currencies import NbpRate, is_currency_code

GROSZ = Decimal("0.01")
PLN = "PLN"


class TransactionError(ValueError):
    """A Transaction field the user must correct; the message is shown in the UI (Polish)."""


class TransactionType(StrEnum):
    """Values are stored in the database, so never rename them."""

    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    BUY = "buy"
    SELL = "sell"
    CURRENCY_EXCHANGE = "currency_exchange"

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
    TransactionType.CURRENCY_EXCHANGE: "Wymiana walut",
}


@dataclass(frozen=True)
class TransactionDraft:
    """The user-entered fields of a Transaction, validated on creation. ``actual_amount`` is positive PLN.

    A Buy or Sell also carries its Instrument, quantity, unit price (in the Instrument's currency) and PLN commission;
    build it with ``buy_or_sell``. One of a foreign-currency Instrument also carries the NBP Rate (D-1) for its Tax
    Amount and, if the user gave one, ``fx_rate``: the rate the Actual Amount was converted at. ``cash_currency`` is
    the Cash Currency it is paid from or into: PLN, or the Instrument's own currency (the commission stays in PLN).
    ``fx_conversion_fee_percent`` is the Account's FX Conversion Fee when the broker converted a foreign-currency one
    paid in PLN: its Actual Amount then comes from the PLN the broker charged, not from a rate, and the fee in PLN
    follows from it like the Tax Amount follows from the NBP Rate.

    A Currency Exchange (build it with ``currency_exchange``) swaps ``quantity`` units of the foreign
    ``cash_currency`` for ``actual_amount`` PLN: buying them, or selling them if ``to_pln``.
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
    cash_currency: str = field(default=PLN, kw_only=True)
    to_pln: bool = field(default=False, kw_only=True)
    fx_conversion_fee_percent: Decimal | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if not self.actual_amount > 0:
            raise TransactionError("Kwota musi być większa od zera.")
        if self.actual_amount != self.actual_amount.quantize(GROSZ):
            raise TransactionError("Kwotę podaj z dokładnością do grosza.")
        trade_fields = (
            self.instrument_id,
            self.quantity,
            self.price,
            self.fx_rate,
            self.nbp_rate,
            self.fx_conversion_fee_percent,
        )
        if self.transaction_type.is_buy_or_sell:
            if self.instrument_id is None:
                raise TransactionError("Wybierz instrument.")
            _check_buy_or_sell_fields(self.quantity, self.price, self.commission)
            _check_rates(self.fx_rate, self.nbp_rate)
            _check_settlement(self.cash_currency, self.nbp_rate)
            if self.fx_conversion_fee_percent is not None:
                _check_conversion(self.fx_conversion_fee_percent, self.fx_rate, self.nbp_rate, self.cash_currency)
        elif self.transaction_type is TransactionType.CURRENCY_EXCHANGE:
            if self.instrument_id is not None or self.price is not None or self.commission:
                raise TransactionError("Wymiana walut nie dotyczy instrumentu.")
            if self.fx_rate is not None or self.nbp_rate is not None or self.fx_conversion_fee_percent is not None:
                raise TransactionError("Kurs wymiany wynika z obu kwot.")
            _check_exchange_fields(self.cash_currency, self.quantity)
        elif any(value is not None for value in trade_fields) or self.commission:
            raise TransactionError(f"{self.transaction_type.label} nie dotyczy instrumentu.")
        elif self.cash_currency != PLN:
            raise TransactionError(f"{self.transaction_type.label} jest na razie możliwa tylko w PLN.")
        if self.to_pln and self.transaction_type is not TransactionType.CURRENCY_EXCHANGE:
            raise TransactionError("Kierunek wymiany dotyczy tylko wymiany walut.")
        object.__setattr__(self, "comment", self.comment.strip())

    @property
    def tax_amount(self) -> Decimal:
        """The PLN amount at the NBP Rate, for tax reports; equal to the Actual Amount for PLN Transactions.

        The FX Conversion Fee is a cost like the commission (deductible in PIT-38, spec 3.3).
        """
        if self.nbp_rate is None:
            return self.actual_amount
        assert self.quantity is not None and self.price is not None  # a Buy or Sell, checked on creation
        costs = self.commission + (self.fx_conversion_fee or Decimal(0))
        return _with_commission(self.transaction_type, _pln(self._settled_value * self.nbp_rate.rate), costs)

    @property
    def converted_amount(self) -> Decimal:
        """The Actual Amount of a Buy or Sell without its commission: what quantity × price alone cost or brought."""
        return _with_commission(self.transaction_type, self.actual_amount, -self.commission)

    @property
    def effective_fx_rate(self) -> Decimal:
        """The PLN per unit of the Instrument's currency that quantity × price really cost or brought."""
        assert self.quantity is not None and self.price is not None  # a Buy or Sell
        return self.converted_amount / (self.quantity * self.price)

    @property
    def fx_conversion_fee(self) -> Decimal | None:
        """The broker's FX Conversion Fee in PLN, a cost of the trade; None unless the broker converted it."""
        if self.fx_conversion_fee_percent is None:
            return None
        return BrokerConversion(self.converted_amount, self.fx_conversion_fee_percent).fee(self.transaction_type)

    @property
    def cash_change(self) -> Decimal:
        """How the Transaction moves the Account's PLN Cash Balance.

        A Buy or Sell paid from foreign cash takes only its commission from PLN.
        """
        if self.is_paid_in_foreign_cash:
            return -self.commission
        return self.actual_cash_change

    @property
    def actual_cash_change(self) -> Decimal:
        """The Actual Amount with the sign of the cash it moves: what a Buy cost, what a Sell brought."""
        return self.actual_amount if self._is_incoming else -self.actual_amount

    @property
    def tax_cash_change(self) -> Decimal:
        """The Tax Amount with the sign of ``actual_cash_change``."""
        return self.tax_amount if self._is_incoming else -self.tax_amount

    @property
    def is_paid_in_foreign_cash(self) -> bool:
        """A Buy or Sell paid from (or into) foreign cash rather than PLN."""
        return self.transaction_type.is_buy_or_sell and self.cash_currency != PLN

    @property
    def foreign_cash_change(self) -> Decimal:
        """How the Transaction moves the Account's Cash Balance in ``cash_currency``; 0 when that is PLN."""
        if self.transaction_type is TransactionType.CURRENCY_EXCHANGE:
            assert self.quantity is not None  # checked on creation
            return -self.quantity if self.to_pln else self.quantity
        if not self.is_paid_in_foreign_cash:
            return Decimal(0)
        return self._settled_value if self._is_incoming else -self._settled_value

    def cash_change_in(self, currency: str) -> Decimal:
        """How the Transaction moves the Account's Cash Balance in ``currency``."""
        if currency == PLN:
            return self.cash_change
        return self.foreign_cash_change if currency == self.cash_currency else Decimal(0)

    @property
    def _settled_value(self) -> Decimal:
        """Quantity × price in the Instrument's currency; to the cent when paid from foreign cash."""
        assert self.quantity is not None and self.price is not None
        value = self.quantity * self.price
        return _pln(value) if self.is_paid_in_foreign_cash else value

    @property
    def _is_incoming(self) -> bool:
        if self.transaction_type is TransactionType.CURRENCY_EXCHANGE:
            return self.to_pln
        return self.transaction_type in (TransactionType.DEPOSIT, TransactionType.SELL)


@dataclass(frozen=True)
class BrokerConversion:
    """The broker converted a foreign-currency trade on a PLN Account: it charged (or, for a Sell, credited)
    ``charged`` PLN for quantity × price, at the market rate worsened by ``fee_percent``, the Account's FX Conversion
    Fee (spec 3.3)."""

    charged: Decimal
    fee_percent: Decimal

    def fee(self, transaction_type: TransactionType) -> Decimal:
        """The fee in PLN: a Buy is charged ``fee_percent`` above the market value, a Sell credited that below it."""
        share = self.fee_percent / 100
        if transaction_type is TransactionType.SELL:
            return _pln(self.charged / (1 - share) - self.charged)
        return _pln(self.charged - self.charged / (1 + share))


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
    cash_currency: str = PLN,
    conversion: BrokerConversion | None = None,
) -> TransactionDraft:
    """A Buy or Sell: in PLN, a Buy costs quantity × price × rate plus commission, a Sell brings that minus it.

    The rate is 1 for a PLN Instrument; for a foreign-currency one it is ``fx_rate`` if the user gave one, otherwise
    the NBP Rate, which ``nbp_rate`` must then carry. Paid from foreign cash (``cash_currency``), quantity × price
    moves that cash to the cent, and the PLN amount values that at the same rate. With a broker ``conversion``,
    quantity × price is worth the PLN the broker charged, and the trade records its FX Conversion Fee.
    """
    _check_buy_or_sell_fields(quantity, price, commission)
    _check_rates(fx_rate, nbp_rate)
    _check_settlement(cash_currency, nbp_rate)
    fee_percent = None
    if conversion is None:
        rate = fx_rate or (nbp_rate.rate if nbp_rate else Decimal(1))
        settled_value = quantity * price if cash_currency == PLN else _pln(quantity * price)
        value = _pln(settled_value * rate)
    else:
        _check_charged(conversion.charged)
        fee_percent = conversion.fee_percent
        _check_conversion(fee_percent, fx_rate, nbp_rate, cash_currency)
        value = conversion.charged
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
        cash_currency=cash_currency,
        fx_conversion_fee_percent=fee_percent,
    )


def currency_exchange(
    account_id: int,
    day: date,
    currency: str,
    foreign_amount: Decimal,
    pln_amount: Decimal,
    *,
    to_pln: bool = False,
    comment: str = "",
) -> TransactionDraft:
    """A Currency Exchange: ``foreign_amount`` of ``currency`` bought for ``pln_amount`` PLN, or sold if ``to_pln``."""
    return TransactionDraft(
        account_id,
        day,
        TransactionType.CURRENCY_EXCHANGE,
        pln_amount,
        comment,
        quantity=foreign_amount,
        cash_currency=currency,
        to_pln=to_pln,
    )


AUTOMATIC_EXCHANGE_COMMENT = "Wymiana automatyczna"


def covering_exchange(buy: TransactionDraft) -> TransactionDraft:
    """The Exchange from PLN that buys exactly the foreign cash ``buy`` spends, on its day and at its rate (spec 3.3).

    The PLN commission is paid from PLN, so it never adds to the foreign amount (spec 3.5, sheet bug 9.8).
    """
    if buy.transaction_type is not TransactionType.BUY or not buy.is_paid_in_foreign_cash:
        raise TransactionError("Automatyczna wymiana walut służy tylko do zakupu za gotówkę w walucie obcej.")
    return currency_exchange(
        buy.account_id,
        buy.date,
        buy.cash_currency,
        -buy.foreign_cash_change,
        buy.actual_amount - buy.commission,
        comment=AUTOMATIC_EXCHANGE_COMMENT,
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


def _check_settlement(cash_currency: str, nbp_rate: NbpRate | None) -> None:
    """Foreign cash pays only for an Instrument in that same currency."""
    if cash_currency != PLN and (nbp_rate is None or nbp_rate.currency != cash_currency):
        raise TransactionError(f"Gotówką {cash_currency} można płacić tylko za instrument w {cash_currency}.")


def _check_charged(charged: Decimal) -> None:
    if not charged > 0:
        raise TransactionError("Kwota pobrana przez brokera musi być większa od zera.")
    if charged != charged.quantize(GROSZ):
        raise TransactionError("Kwota pobrana przez brokera musi być podana z dokładnością do grosza.")


def _check_conversion(
    fee_percent: Decimal, fx_rate: Decimal | None, nbp_rate: NbpRate | None, cash_currency: str
) -> None:
    """The broker converts only a foreign-currency trade paid in PLN, and what it charged replaces the user's rate."""
    if nbp_rate is None:
        raise TransactionError("Przewalutowanie dotyczy tylko instrumentu w walucie obcej.")
    if cash_currency != PLN:
        raise TransactionError("Przewalutowanie dotyczy tylko transakcji płatnej w PLN.")
    if fx_rate is not None:
        raise TransactionError("Przy przewalutowaniu przez brokera kurs wynika z pobranej kwoty.")
    if not 0 <= fee_percent < 100:
        raise TransactionError("Opłata za przewalutowanie musi wynosić co najmniej 0% i mniej niż 100%.")


def _check_exchange_fields(currency: str, quantity: Decimal | None) -> None:
    if currency == PLN or not is_currency_code(currency):
        raise TransactionError("Wybierz walutę obcą do wymiany.")
    if quantity is None or not quantity > 0:
        raise TransactionError("Kwota w walucie musi być większa od zera.")
    if quantity != quantity.quantize(GROSZ):
        raise TransactionError("Kwotę w walucie podaj z dokładnością do setnych.")


def _check_buy_or_sell_fields(quantity: Decimal | None, price: Decimal | None, commission: Decimal) -> None:
    if quantity is None or not quantity > 0:
        raise TransactionError("Liczba musi być większa od zera.")
    if price is None or not price > 0:
        raise TransactionError("Cena musi być większa od zera.")
    if commission < 0:
        raise TransactionError("Prowizja nie może być ujemna.")
    if commission != commission.quantize(GROSZ):
        raise TransactionError("Prowizję podaj z dokładnością do grosza.")


def cash_balances(
    transactions: Iterable[TransactionDraft], on: date | None = None, currency: str = PLN
) -> dict[int, Decimal]:
    """Cash Balance in ``currency`` per Account id at the end of ``on`` (default: all Transactions).

    A balance may go negative: insufficient cash only warns (spec 3.3), so history can be entered in any order.
    """
    balances: dict[int, Decimal] = {}
    for transaction in transactions:
        if on is None or transaction.date <= on:
            balances[transaction.account_id] = balances.get(transaction.account_id, Decimal(0)) + (
                transaction.cash_change_in(currency)
            )
    return balances


def lowest_cash_balance(
    transactions: Iterable[TransactionDraft], account_id: int, start: date, currency: str = PLN
) -> Decimal:
    """The lowest end-of-day Cash Balance in ``currency`` of the Account from ``start`` on.

    Below zero means some Transaction lacks cash, which warns but does not block (spec 3.3).
    """
    own = [t for t in transactions if t.account_id == account_id]
    days = sorted({start} | {t.date for t in own if t.date >= start})
    return min(cash_balances(own, on=day, currency=currency).get(account_id, Decimal(0)) for day in days)
