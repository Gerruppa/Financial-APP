"""Transactions and the Cash Balances they produce (spec 3.3, 3.5).

For now: PLN Deposits, Withdrawals and Costs, Buys and Sells (paid in PLN, optionally converted by the broker for an
FX Conversion Fee, or, on an Account holding the Instrument's currency, from that foreign cash), Currency Exchanges
between PLN and a foreign Cash Currency, Dividends (and interest) paid into PLN or foreign cash, and DRIPs.
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
    DIVIDEND = "dividend"
    COST = "cost"
    CURRENCY_EXCHANGE = "currency_exchange"
    DRIP = "drip"
    SPLIT = "split"
    CASH_TRANSFER = "cash_transfer"
    SECURITY_TRANSFER = "security_transfer"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def is_buy_or_sell(self) -> bool:
        """A Buy or Sell, which moves an Instrument as well as cash."""
        return self in (TransactionType.BUY, TransactionType.SELL)

    @property
    def is_dividend(self) -> bool:
        """A Dividend (or interest), paid out or, as a DRIP, reinvested: it has a gross amount and withholding tax."""
        return self in (TransactionType.DIVIDEND, TransactionType.DRIP)

    @property
    def settles_in_cash_currency(self) -> bool:
        """A Buy or Sell paid from, or a Dividend paid into, PLN or foreign cash of its own currency."""
        return self in (TransactionType.BUY, TransactionType.SELL, TransactionType.DIVIDEND)

    @property
    def opens_lot(self) -> bool:
        """A Buy, or a DRIP buying units with its Dividend."""
        return self in (TransactionType.BUY, TransactionType.DRIP)

    @property
    def has_amount(self) -> bool:
        """Every Transaction but a Split or a Security Transfer, which move only units, has a PLN amount."""
        return self not in (TransactionType.SPLIT, TransactionType.SECURITY_TRANSFER)

    @property
    def is_transfer(self) -> bool:
        """A Cash or Security Transfer, from its Account to a target Account."""
        return self in (TransactionType.CASH_TRANSFER, TransactionType.SECURITY_TRANSFER)


_LABELS = {
    TransactionType.DEPOSIT: "Wpłata",
    TransactionType.WITHDRAWAL: "Wypłata",
    TransactionType.BUY: "Zakup",
    TransactionType.SELL: "Sprzedaż",
    TransactionType.DIVIDEND: "Dywidenda / odsetki",
    TransactionType.COST: "Koszty",
    TransactionType.CURRENCY_EXCHANGE: "Wymiana walut",
    TransactionType.DRIP: "DRIP",
    TransactionType.SPLIT: "Split",
    TransactionType.CASH_TRANSFER: "Transfer gotówki",
    TransactionType.SECURITY_TRANSFER: "Transfer papierów",
}


class Origin(StrEnum):
    """Where a Transaction came from (spec 7). Values are stored in the database, so never rename them."""

    MANUAL = "manual"
    SPREADSHEET = "spreadsheet"

    @property
    def label(self) -> str:
        return "import z arkusza" if self is Origin.SPREADSHEET else "ręczna"


@dataclass(frozen=True)
class SplitRatio:
    """A Split X:Y: every ``old`` units become ``new`` ones, so open Lots hold X/Y times as many units at the same
    cost (spec 3.5)."""

    new: int
    old: int

    def __post_init__(self) -> None:
        if not (self.new > 0 and self.old > 0):
            raise TransactionError("Obie liczby splitu X:Y muszą być większe od zera.")
        if self.new == self.old:
            raise TransactionError("Split X:Y musi zmieniać liczbę jednostek (X różne od Y).")

    def rescale(self, quantity: Decimal) -> Decimal:
        """``quantity`` units after the Split; multiplying first keeps it exact whenever it can be (3 at 1:3 is 1)."""
        return quantity * self.new / self.old

    def __str__(self) -> str:
        return f"{self.new}:{self.old}"


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

    A Dividend (build it with ``dividend``; interest too, with or without an Instrument) carries its ``gross`` amount
    and the ``withholding_tax`` taken at source, both in its ``dividend_currency``: the Instrument's, so a foreign one
    also carries the NBP Rate and optionally ``fx_rate`` like a Buy. Its net amount goes into ``cash_currency``: PLN,
    converted into the Actual Amount, or foreign cash of the same currency, worth the Actual Amount. A DRIP (build it
    with ``drip``) is a Dividend whose net amount buys ``quantity`` units of its Instrument instead: it leaves cash
    alone and opens a Lot costing that amount. A Cost (build it with ``cost``) is an amount the Account paid, like a
    Withdrawal: in PLN, or ``quantity`` of a foreign ``cash_currency`` worth the Actual Amount at the NBP Rate.

    A Split (build it with ``split``) rescales the open Lots of its Instrument on the Account by its ``split_ratio``.
    A Cash Transfer (``cash_transfer``) moves ``actual_amount`` PLN, a Security Transfer (``security_transfer``)
    ``quantity`` units of its Instrument with their Lots, to ``target_account_id``. A Split and a Security Transfer
    move no cash, so their ``actual_amount`` is 0.
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
    gross: Decimal | None = field(default=None, kw_only=True)
    withholding_tax: Decimal = field(default=Decimal(0), kw_only=True)
    target_account_id: int | None = field(default=None, kw_only=True)
    split_ratio: SplitRatio | None = field(default=None, kw_only=True)
    origin: Origin = field(default=Origin.MANUAL, kw_only=True)
    # Imported Transactions only: the fingerprint of their spreadsheet row, so importing the file again skips them
    external_id: str | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if not self.transaction_type.has_amount:
            if self.actual_amount:
                raise TransactionError(f"{self.transaction_type.label} nie ma kwoty.")
        elif not self.actual_amount > 0:
            raise TransactionError("Kwota musi być większa od zera.")
        elif self.actual_amount != self.actual_amount.quantize(GROSZ):
            raise TransactionError("Kwotę podaj z dokładnością do grosza.")
        self._check_target()
        if self.transaction_type is TransactionType.SPLIT and self.split_ratio is None:
            raise TransactionError("Podaj split w postaci X:Y, np. 2:1.")
        if self.transaction_type is not TransactionType.SPLIT and self.split_ratio is not None:
            raise TransactionError(f"{self.transaction_type.label} nie ma splitu.")
        trade_fields = (
            self.instrument_id,
            self.quantity,
            self.price,
            self.fx_rate,
            self.nbp_rate,
            self.fx_conversion_fee_percent,
        )
        if not self.transaction_type.is_dividend and (self.gross is not None or self.withholding_tax):
            raise TransactionError(f"{self.transaction_type.label} nie ma kwoty brutto ani podatku u źródła.")
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
        elif self.transaction_type.is_dividend:
            self._check_dividend()
        elif not self.transaction_type.has_amount:
            self._check_units_only()
        elif self.transaction_type is TransactionType.COST and self.cash_currency != PLN:
            self._check_foreign_cost()
        elif any(value is not None for value in trade_fields) or self.commission:
            raise TransactionError(f"{self.transaction_type.label} nie dotyczy instrumentu.")
        elif self.cash_currency != PLN:
            raise TransactionError(f"{self.transaction_type.label} jest na razie możliwa tylko w PLN.")
        if self.to_pln and self.transaction_type is not TransactionType.CURRENCY_EXCHANGE:
            raise TransactionError("Kierunek wymiany dotyczy tylko wymiany walut.")
        object.__setattr__(self, "comment", self.comment.strip())

    def _check_target(self) -> None:
        """A Transfer goes to another Account; nothing else has a target."""
        if not self.transaction_type.is_transfer:
            if self.target_account_id is not None:
                raise TransactionError(f"{self.transaction_type.label} nie ma konta docelowego.")
            return
        if self.target_account_id is None:
            raise TransactionError("Wybierz konto docelowe.")
        if self.target_account_id == self.account_id:
            raise TransactionError("Konto docelowe musi być inne niż konto źródłowe.")

    def _check_units_only(self) -> None:
        """A Split or a Security Transfer: an Instrument and, for a Transfer, its units, with no price or rate."""
        label = self.transaction_type.label
        if self.instrument_id is None:
            raise TransactionError("Wybierz instrument.")
        rates = (self.price, self.fx_rate, self.nbp_rate, self.fx_conversion_fee_percent)
        if any(value is not None for value in rates) or self.commission or self.cash_currency != PLN:
            raise TransactionError(f"{label} nie ma ceny, prowizji ani kursu.")
        if self.transaction_type is TransactionType.SPLIT:
            if self.quantity is not None:
                raise TransactionError("Split nie ma liczby jednostek, tylko proporcję X:Y.")
        elif self.quantity is None or not self.quantity > 0:
            raise TransactionError("Liczba musi być większa od zera.")

    def _check_dividend(self) -> None:
        label = self.transaction_type.label
        if self.price is not None or self.commission:
            raise TransactionError(f"{label} nie ma ceny ani prowizji.")
        _check_dividend_amounts(self.gross, self.withholding_tax)
        _check_rates(self.fx_rate, self.nbp_rate)
        if self.fx_conversion_fee_percent is not None:
            if self.transaction_type is TransactionType.DRIP:
                raise TransactionError("DRIP nie przewalutowuje, więc liczy się po kursie NBP.")
            _check_conversion(self.fx_conversion_fee_percent, self.fx_rate, self.nbp_rate, self.cash_currency)
        if self.cash_currency not in (PLN, self.dividend_currency):
            raise TransactionError(f"Na gotówkę {self.cash_currency} trafia tylko dywidenda w {self.cash_currency}.")
        if self.nbp_rate is None and self.actual_amount != self.net:
            raise TransactionError("Kwota dywidendy w PLN musi być równa kwocie netto.")
        if self.transaction_type is TransactionType.DRIP:
            if self.instrument_id is None:
                raise TransactionError("Wybierz instrument.")
            if self.quantity is None or not self.quantity > 0:
                raise TransactionError("Liczba musi być większa od zera.")
            if self.cash_currency != PLN:
                raise TransactionError("DRIP nie zmienia gotówki.")
            if self.fx_rate is not None:
                raise TransactionError("DRIP nie przewalutowuje, więc liczy się po kursie NBP.")
        elif self.quantity is not None:
            raise TransactionError(f"{label} nie ma liczby jednostek.")

    def _check_foreign_cost(self) -> None:
        """A Cost paid from foreign cash: ``quantity`` of it, worth the Actual Amount at the NBP Rate."""
        if self.instrument_id is not None or self.price is not None or self.commission:
            raise TransactionError("Koszty nie dotyczą instrumentu.")
        if self.fx_rate is not None or self.fx_conversion_fee_percent is not None:
            raise TransactionError("Koszty w walucie liczą się po kursie NBP.")
        if self.nbp_rate is None or self.nbp_rate.currency != self.cash_currency:
            raise TransactionError(f"Brak kursu NBP {self.cash_currency}. Zapis zablokowany.")
        if self.quantity is None or not self.quantity > 0:
            raise TransactionError("Kwota musi być większa od zera.")
        if self.quantity != self.quantity.quantize(GROSZ):
            raise TransactionError("Kwotę w walucie podaj z dokładnością do setnych.")
        if self.actual_amount != _pln(self.quantity * self.nbp_rate.rate):
            raise TransactionError("Kwota kosztów w PLN musi wynikać z kursu NBP.")

    @property
    def net(self) -> Decimal:
        """A Dividend's gross amount less the withholding tax, in its ``dividend_currency``."""
        assert self.gross is not None  # a Dividend or DRIP, checked on creation
        return self.gross - self.withholding_tax

    @property
    def dividend_currency(self) -> str:
        """The currency of a Dividend's amounts: the NBP Rate's, or PLN."""
        return PLN if self.nbp_rate is None else self.nbp_rate.currency

    @property
    def tax_amount(self) -> Decimal:
        """The PLN amount at the NBP Rate, for tax reports; equal to the Actual Amount for PLN Transactions.

        The FX Conversion Fee is a cost like the commission (deductible in PIT-38, spec 3.3). A Dividend's is its net
        amount at the NBP Rate.
        """
        if self.nbp_rate is None:
            return self.actual_amount
        if self.transaction_type.is_dividend:
            return _pln(self.net * self.nbp_rate.rate)
        if self.transaction_type is TransactionType.COST:
            return self.actual_amount  # already at the NBP Rate
        assert self.quantity is not None and self.price is not None  # a Buy or Sell, checked on creation
        costs = self.commission + (self.fx_conversion_fee or Decimal(0))
        return _with_commission(self.transaction_type, _pln(self._settled_value * self.nbp_rate.rate), costs)

    @property
    def converted_amount(self) -> Decimal:
        """The Actual Amount of a Buy or Sell without its commission: what quantity × price alone cost or brought."""
        return _with_commission(self.transaction_type, self.actual_amount, -self.commission)

    @property
    def effective_fx_rate(self) -> Decimal:
        """The PLN per unit of the Instrument's currency that quantity × price (a Dividend's net amount) really cost
        or brought."""
        if self.transaction_type.is_dividend:
            return self.converted_amount / self.net
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

        A Buy or Sell paid from foreign cash takes only its commission from PLN; a DRIP, a Split and a Security
        Transfer never touch cash. A Cash Transfer is seen from its source Account: the target gains what it loses.
        """
        if self.transaction_type is TransactionType.DRIP or not self.transaction_type.has_amount:
            return Decimal(0)
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
        """A Buy, Sell, Dividend or Cost paid from (or into) foreign cash rather than PLN."""
        paid = self.transaction_type.settles_in_cash_currency or self.transaction_type is TransactionType.COST
        return paid and self.cash_currency != PLN

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
        """Quantity × price in the Instrument's currency, to the cent when paid from foreign cash; a Dividend's net;
        a Cost's foreign amount."""
        if self.transaction_type.is_dividend:
            return self.net
        if self.transaction_type is TransactionType.COST:
            assert self.quantity is not None  # checked on creation
            return self.quantity
        assert self.quantity is not None and self.price is not None
        value = self.quantity * self.price
        return _pln(value) if self.is_paid_in_foreign_cash else value

    @property
    def _is_incoming(self) -> bool:
        if self.transaction_type is TransactionType.CURRENCY_EXCHANGE:
            return self.to_pln
        return self.transaction_type in (TransactionType.DEPOSIT, TransactionType.SELL, TransactionType.DIVIDEND)


@dataclass(frozen=True)
class BrokerConversion:
    """The broker converted a foreign-currency trade or Dividend on a PLN Account: it charged (or, for a Sell or
    Dividend, credited) ``charged`` PLN for quantity × price (or the net Dividend), at the market rate worsened by
    ``fee_percent``, the Account's FX Conversion Fee (spec 3.3)."""

    charged: Decimal
    fee_percent: Decimal

    def fee(self, transaction_type: TransactionType) -> Decimal:
        """The fee in PLN: a Buy is charged ``fee_percent`` above the market value, a Sell or Dividend credited that
        below it."""
        share = self.fee_percent / 100
        if transaction_type is not TransactionType.BUY:
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


def dividend(
    account_id: int,
    day: date,
    gross: Decimal,
    withholding_tax: Decimal = Decimal(0),
    comment: str = "",
    *,
    instrument_id: int | None = None,
    fx_rate: Decimal | None = None,
    nbp_rate: NbpRate | None = None,
    cash_currency: str = PLN,
    conversion: BrokerConversion | None = None,
) -> TransactionDraft:
    """A Dividend or interest of ``gross`` less ``withholding_tax``, in the currency of ``nbp_rate`` (else PLN).

    Paid into PLN, its Actual Amount is the net amount at ``fx_rate`` or the NBP Rate, or, with a broker
    ``conversion``, the PLN the broker credited, recording its FX Conversion Fee; paid into foreign cash
    (``cash_currency``), the net amount moves that cash and the Actual Amount values it at the same rate.
    """
    return _dividend_draft(
        TransactionType.DIVIDEND,
        account_id,
        day,
        gross,
        withholding_tax,
        comment,
        instrument_id=instrument_id,
        fx_rate=fx_rate,
        nbp_rate=nbp_rate,
        cash_currency=cash_currency,
        conversion=conversion,
    )


def drip(
    account_id: int,
    day: date,
    instrument_id: int,
    quantity: Decimal,
    gross: Decimal,
    withholding_tax: Decimal = Decimal(0),
    comment: str = "",
    *,
    nbp_rate: NbpRate | None = None,
) -> TransactionDraft:
    """A Dividend of the Instrument reinvested into ``quantity`` more units of it: a Lot costing the net amount in PLN,
    with no cash moving. Nothing is converted, so a foreign-currency one costs the net amount at the NBP Rate."""
    return _dividend_draft(
        TransactionType.DRIP,
        account_id,
        day,
        gross,
        withholding_tax,
        comment,
        instrument_id=instrument_id,
        quantity=quantity,
        nbp_rate=nbp_rate,
    )


def _dividend_draft(
    kind: TransactionType,
    account_id: int,
    day: date,
    gross: Decimal,
    withholding_tax: Decimal,
    comment: str,
    *,
    instrument_id: int | None,
    quantity: Decimal | None = None,
    fx_rate: Decimal | None = None,
    nbp_rate: NbpRate | None,
    cash_currency: str = PLN,
    conversion: BrokerConversion | None = None,
) -> TransactionDraft:
    _check_dividend_amounts(gross, withholding_tax)
    _check_rates(fx_rate, nbp_rate)
    fee_percent = None
    if conversion is None:
        rate = fx_rate or (nbp_rate.rate if nbp_rate else Decimal(1))
        actual_amount = _pln((gross - withholding_tax) * rate)
    else:
        _check_charged(conversion.charged)
        fee_percent = conversion.fee_percent
        _check_conversion(fee_percent, fx_rate, nbp_rate, cash_currency)
        actual_amount = conversion.charged
    if actual_amount.is_zero():
        raise TransactionError("Kwota netto musi wynosić co najmniej 0,01 zł.")
    return TransactionDraft(
        account_id,
        day,
        kind,
        actual_amount,
        comment,
        instrument_id=instrument_id,
        quantity=quantity,
        fx_rate=fx_rate,
        nbp_rate=nbp_rate,
        cash_currency=cash_currency,
        gross=gross,
        withholding_tax=withholding_tax,
        fx_conversion_fee_percent=fee_percent,
    )


def cost(
    account_id: int,
    day: date,
    amount: Decimal,
    comment: str = "",
    *,
    cash_currency: str = PLN,
    nbp_rate: NbpRate | None = None,
) -> TransactionDraft:
    """A Cost of ``amount`` in ``cash_currency``: PLN, or foreign cash, worth its amount at the NBP Rate (its Actual
    and Tax Amount), which ``nbp_rate`` must then carry."""
    if cash_currency == PLN:
        return TransactionDraft(account_id, day, TransactionType.COST, amount, comment)
    if nbp_rate is None or nbp_rate.currency != cash_currency:
        raise TransactionError(f"Brak kursu NBP {cash_currency}. Zapis zablokowany.")
    return TransactionDraft(
        account_id,
        day,
        TransactionType.COST,
        _pln(amount * nbp_rate.rate),
        comment,
        quantity=amount,
        nbp_rate=nbp_rate,
        cash_currency=cash_currency,
    )


def split(account_id: int, day: date, instrument_id: int, ratio: SplitRatio, comment: str = "") -> TransactionDraft:
    """A Split X:Y of the Instrument on the Account: its open Lots get X/Y times the units at the same cost."""
    return TransactionDraft(
        account_id, day, TransactionType.SPLIT, Decimal(0), comment, instrument_id=instrument_id, split_ratio=ratio
    )


def cash_transfer(
    account_id: int, day: date, target_account_id: int, amount: Decimal, comment: str = ""
) -> TransactionDraft:
    """``amount`` PLN moving from the Account to ``target_account_id``."""
    return TransactionDraft(
        account_id, day, TransactionType.CASH_TRANSFER, amount, comment, target_account_id=target_account_id
    )


def security_transfer(
    account_id: int, day: date, target_account_id: int, instrument_id: int, quantity: Decimal, comment: str = ""
) -> TransactionDraft:
    """``quantity`` units of the Instrument moving to ``target_account_id`` with the dates and costs of their Lots."""
    return TransactionDraft(
        account_id,
        day,
        TransactionType.SECURITY_TRANSFER,
        Decimal(0),
        comment,
        instrument_id=instrument_id,
        quantity=quantity,
        target_account_id=target_account_id,
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


def _check_dividend_amounts(gross: Decimal | None, withholding_tax: Decimal) -> None:
    if gross is None or not gross > 0:
        raise TransactionError("Kwota brutto musi być większa od zera.")
    if gross != gross.quantize(GROSZ):
        raise TransactionError("Kwotę brutto podaj z dokładnością do grosza.")
    if not 0 <= withholding_tax < gross:
        raise TransactionError("Podatek u źródła musi wynosić co najmniej 0 i mniej niż kwota brutto.")
    if withholding_tax != withholding_tax.quantize(GROSZ):
        raise TransactionError("Podatek u źródła podaj z dokładnością do grosza.")


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

    A balance may go negative: insufficient cash only warns (spec 3.3), so history can be entered in any order. A
    Cash Transfer brings its target Account what it takes from its source.
    """
    balances: dict[int, Decimal] = {}
    for transaction in transactions:
        if on is None or transaction.date <= on:
            change = transaction.cash_change_in(currency)
            balances[transaction.account_id] = balances.get(transaction.account_id, Decimal(0)) + change
            target = transaction.target_account_id
            if target is not None:
                balances[target] = balances.get(target, Decimal(0)) - change
    return balances


def lowest_cash_balance(
    transactions: Iterable[TransactionDraft], account_id: int, start: date, currency: str = PLN
) -> Decimal:
    """The lowest end-of-day Cash Balance in ``currency`` of the Account from ``start`` on.

    Below zero means some Transaction lacks cash, which warns but does not block (spec 3.3).
    """
    own = [t for t in transactions if account_id in (t.account_id, t.target_account_id)]
    days = sorted({start} | {t.date for t in own if t.date >= start})
    return min(cash_balances(own, on=day, currency=currency).get(account_id, Decimal(0)) for day in days)


def costs_by_account(transactions: Iterable[TransactionDraft]) -> dict[int, Decimal]:
    """Commissions and costs in PLN per Account id: Costs, commissions and FX Conversion Fees (spec section 5)."""
    costs: dict[int, Decimal] = {}
    for t in transactions:
        if t.transaction_type is TransactionType.COST:
            cost = t.actual_amount
        else:
            cost = t.commission + (t.fx_conversion_fee or Decimal(0))
        if cost:
            costs[t.account_id] = costs.get(t.account_id, Decimal(0)) + cost
    return costs


def dividends_by_account(transactions: Iterable[TransactionDraft]) -> dict[int, Decimal]:
    """Net Dividends and interest in PLN per Account id (their Actual Amounts), reinvested ones included."""
    totals: dict[int, Decimal] = {}
    for t in transactions:
        if t.transaction_type.is_dividend:
            totals[t.account_id] = totals.get(t.account_id, Decimal(0)) + t.actual_amount
    return totals
