"""The transaction dialog's rules as a model without widgets (#111): given what the form holds (``FormState``) it gives
the fields to show with their options and labels (``FormLayout``) and the ``TransactionDraft`` they describe, or the
error of the field that does not read (``FormError``). The dialog in ``ui/transactions.py`` only binds widgets to it.

For now: Deposits, Withdrawals and Costs (in PLN or foreign cash), Currency Exchanges, Buys and Sells
(foreign-currency ones paid from foreign cash or in PLN, converted at the user's rate, the NBP Rate (D-1) or by the
broker for its FX Conversion Fee), Dividends and interest (paid into PLN or foreign cash the same way), DRIPs,
Splits, and PLN Cash Transfers and Security Transfers to another Account. A Buy of retail treasury bonds has its bond
mode: the type and the purchase date give the Bond Series (spec 3.4.1), unless the user picks another (L-26). A Sell
of a Bond Series is an Early Redemption: it picks its Lot, the oldest by default, and is prefilled with the gross
value of one bond, the early-redemption fee and the tax withheld (ADR-0007).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal

from financial_app.domain.accounts import Account, AccountType, tax_regime_for
from financial_app.domain.bond_redemption import EarlyRedemption, early_redemption
from financial_app.domain.bond_valuation import BondData
from financial_app.domain.bonds import (
    ISSUE_PRICE,
    BondSeries,
    BondType,
    SeriesTerms,
    bond_type_of,
    series_name,
    series_of_type,
    sold_on,
)
from financial_app.domain.currencies import MissingNbpRateError, NbpRate
from financial_app.domain.formatting import (
    currency_unit,
    format_amount,
    format_date,
    format_exact,
    format_percent,
    format_pln,
    format_quantity,
    parse_date,
    parse_number,
    parse_ratio,
)
from financial_app.domain.instruments import Instrument
from financial_app.domain.lots import Lot, open_lots
from financial_app.domain.transactions import (
    PLN,
    BrokerConversion,
    SplitRatio,
    Transaction,
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    cash_transfer,
    cost,
    currency_exchange,
    deposit_or_withdrawal,
    dividend,
    drip,
    security_transfer,
    split,
)

# Offered for buying a foreign currency in a Currency Exchange, so the first exchange needs no setup
SUGGESTED_EXCHANGE_CURRENCIES = ("USD", "EUR")
# Currency Exchange directions: buying the foreign currency for PLN, or selling it for PLN
BUY_CURRENCY, SELL_CURRENCY = "buy", "sell"
TRANSACTION_TYPE_OPTIONS = {transaction_type.value: transaction_type.label for transaction_type in TransactionType}
# The bond types in the order the dialog offers them, the most bought first, with their terms
BOND_TYPE_OPTIONS = {
    BondType.EDO.value: "EDO · 10 lat",
    BondType.COI.value: "COI · 4 lata",
    BondType.TOS.value: "TOS · 3 lata",
    BondType.OTS.value: "OTS · 3 miesiące",
    BondType.ROR.value: "ROR · 1 rok",
    BondType.DOR.value: "DOR · 2 lata",
    BondType.ROS.value: "ROS · 6 lat",
    BondType.ROD.value: "ROD · 12 lat",
}

# What a field that does not read says
AMOUNT_MESSAGE = "Kwota musi być liczbą, np. 1 000,50."
FOREIGN_AMOUNT_MESSAGE = "Kwota w walucie musi być liczbą, np. 1 000,50."
QUANTITY_MESSAGE = "Liczba musi być liczbą, np. 10 lub 0,5."
RATE_MESSAGE = "Kurs musi być liczbą, np. 3,65."
TAX_MESSAGE = "Podatek musi być liczbą, np. 15,00."
INSTRUMENT_MESSAGE = "Wybierz instrument."
# The NBP Rate (D-1) of a currency for a day; raises MissingNbpRateError without one
RateLookup = Callable[[str, date], NbpRate]


class FormError(TransactionError):
    """A field that does not read, named by ``field``: a ``FormTexts`` attribute, ``"day"``, ``"instrument"`` or
    ``"target"``."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class FormTexts:
    """What is typed in the form's text fields."""

    amount: str = ""
    foreign_amount: str = ""
    quantity: str = ""
    price: str = ""
    fx_rate: str = ""
    commission: str = ""
    charged: str = ""
    gross: str = ""
    withholding_tax: str = ""
    ratio: str = ""
    comment: str = ""
    # A Buy's amount to spend, which proposes its quantity and is not saved with it (#120)
    spend: str = ""

    @classmethod
    def of(cls, transaction: Transaction | None) -> FormTexts:
        """The edit-field texts for ``transaction``, exact so that re-saving never rounds a value."""
        if transaction is None:
            return cls()
        comment = transaction.comment
        kind = transaction.transaction_type
        if kind is TransactionType.CURRENCY_EXCHANGE:
            assert transaction.quantity is not None
            return cls(
                amount=format_exact(transaction.actual_amount),
                foreign_amount=format_exact(transaction.quantity),
                comment=comment,
            )
        if kind.is_dividend:
            assert transaction.gross is not None
            return cls(
                quantity="" if transaction.quantity is None else format_quantity(transaction.quantity),
                fx_rate="" if transaction.fx_rate is None else format_exact(transaction.fx_rate),
                gross=format_exact(transaction.gross),
                withholding_tax=format_exact(transaction.withholding_tax),
                # What the broker credited for the net amount
                charged=""
                if transaction.fx_conversion_fee_percent is None
                else format_exact(transaction.actual_amount),
                comment=comment,
            )
        if kind is TransactionType.SPLIT:
            return cls(ratio=str(transaction.split_ratio), comment=comment)
        if kind is TransactionType.SECURITY_TRANSFER:
            assert transaction.quantity is not None
            return cls(quantity=format_quantity(transaction.quantity), comment=comment)
        if kind.moves_cash_amount and transaction.quantity is not None:  # in foreign cash
            return cls(
                amount=format_exact(transaction.quantity),
                fx_rate="" if transaction.fx_rate is None else format_exact(transaction.fx_rate),
                comment=comment,
            )
        if not kind.is_buy_or_sell:
            return cls(amount=format_exact(transaction.actual_amount), comment=comment)
        assert transaction.quantity is not None and transaction.price is not None
        converted = transaction.fx_conversion_fee_percent is not None
        return cls(
            quantity=format_quantity(transaction.quantity),
            price=format_exact(transaction.price),
            fx_rate="" if transaction.fx_rate is None else format_exact(transaction.fx_rate),
            commission=format_exact(transaction.commission),
            withholding_tax=format_exact(transaction.withholding_tax),
            # What the broker charged for quantity × price, the commission aside
            charged=format_exact(transaction.converted_amount) if converted else "",
            comment=comment,
        )


@dataclass(frozen=True)
class FormState:
    """What the form holds: the choices made and the texts typed. A choice no longer offered (say a Cash Currency of
    the Account chosen before) falls back to the default the layout gives."""

    account_id: int
    kind: TransactionType
    day: str
    texts: FormTexts = FormTexts()
    target_id: int | None = None
    instrument_id: int | None = None
    bond_mode: bool = False
    bond_type: BondType = BondType.EDO
    # A Series picked instead of the one the bond type and purchase date give
    series_pick: str | None = None
    rollover: bool = False
    lot_id: int | None = None
    direction: str = BUY_CURRENCY
    exchange_currency: str | None = None
    cash_currency: str | None = None
    dividend_currency: str | None = None
    paid_from: str | None = None
    convert: bool = False
    auto_exchange: bool = False


@dataclass(frozen=True)
class FormPrefill:
    """What a new Transaction's form opens with instead of being empty, e.g. a Recurring Rule's Draft (issue #97): a
    Deposit's amount and currency, or a Buy's Instrument with its quantity and price left to type."""

    account_id: int
    kind: TransactionType
    day: date
    amount: str = ""
    cash_currency: str = PLN
    instrument_id: int | None = None
    comment: str = ""


@dataclass(frozen=True)
class Shown:
    """A field: whether it shows, its label and hint."""

    visible: bool
    label: str = ""
    hint: str = ""


@dataclass(frozen=True)
class Choice[T]:
    """A select: whether it shows, the options offered (value to label) and the value chosen among them."""

    visible: bool
    options: Mapping[T, str] = field(default_factory=dict)
    value: T | None = None
    label: str = ""


@dataclass(frozen=True)
class FormLayout:
    """The fields the chosen type needs, with their options and labels, and the texts shown beside them."""

    amount: Shown
    instrument_fields: bool
    target: Choice[int]
    ratio: bool
    exchange_fields: bool
    direction: Choice[str]
    exchange_currency: Choice[str]
    foreign_amount: Shown
    cash_currency: Choice[str]
    dividend_currency: Choice[str]
    quantity: Shown
    bond_mode: bool
    bond_fields: bool
    series: Choice[str]
    series_text: str
    rollover: bool
    instrument: bool
    lot: Choice[int]
    price: Shown
    commission: bool
    gross: Shown
    withholding_tax: Shown
    net: Shown
    paid_from: Choice[str]
    fx_rate: Shown
    convert: Shown
    charged: Shown
    auto_exchange: bool
    spend: Shown


@dataclass(frozen=True)
class FormContext:
    """What the form reads besides itself: every Account and Instrument, the Transactions in entry order (for the Lots
    an Early Redemption picks), the Bond Series held and those in the MF file, the bond prices, where NBP Rates come
    from and the Transaction being edited, if any."""

    accounts: Sequence[Account]
    instruments: Sequence[Instrument]
    transactions: Sequence[Transaction]
    held_series: Mapping[str, BondSeries]
    mf_terms: Mapping[str, SeriesTerms]
    bond_data: BondData
    rates: RateLookup
    edited: Transaction | None = None


class TransactionForm:
    """The rules of the transaction dialog over a ``FormContext``."""

    def __init__(self, context: FormContext) -> None:
        self.context = context
        edited = self.edited = context.edited
        self._accounts = {a.id: a for a in context.accounts}
        self._instruments = {i.id: i for i in context.instruments}
        # Commissions are in PLN and Accounts without PLN are not supported yet (#124), so only Accounts holding PLN
        # can take part; an edited Transaction keeps offering its own Account even if that has been deactivated since
        self.accounts = {
            a.id: a.name
            for a in context.accounts
            if (a.active and PLN in a.cash_currencies) or (edited is not None and a.id == edited.account_id)
        }
        # A Transfer goes to another of the same Accounts; an edited one keeps offering its own target
        own_target = edited.target_account_id if edited else None
        self.targets = {
            **self.accounts,
            **({own_target: self._accounts[own_target].name} if own_target is not None else {}),
        }
        self.instruments = {i.id: i.name for i in context.instruments}
        self._bond_ids = {i.id for i in context.instruments if i.is_bond_series}
        # An edited Buy of a Bond Series opens in the bond mode, with its type
        self.edited_series = next(
            (
                i.name
                for i in context.instruments
                if edited is not None
                and edited.transaction_type is TransactionType.BUY
                and i.id == edited.instrument_id
                and i.is_bond_series
            ),
            None,
        )
        own_type = bond_type_of(self.edited_series) if self.edited_series else None
        self._own_type = own_type
        # The Series the edited Buy's own type and date give, which may differ from its own (an imported Buy dated on
        # the settlement day, say)
        self._own_name = series_name(own_type, edited.date) if own_type and edited else None
        self._own_cash_currency = edited.cash_currency if edited and edited.transaction_type.moves_cash_amount else PLN
        self._own_dividend_currency = (
            edited.dividend_currency if edited and edited.transaction_type.is_dividend else None
        )
        self._type_series: dict[BondType, dict[str, str]] = {}  # the Series offered for each type, built once

    def initial_state(self, today: date, prefill: FormPrefill | None = None) -> FormState:
        """The form as it opens: empty for a new Transaction or filled with ``prefill``, else filled from the edited
        one."""
        if prefill is not None and self.edited is None and prefill.account_id in self.accounts:
            bought = self._instruments.get(prefill.instrument_id) if prefill.instrument_id is not None else None
            bond_type = bond_type_of(bought.name) if bought is not None and bought.is_bond_series else None
            return FormState(
                account_id=prefill.account_id,
                kind=prefill.kind,
                day=format_date(prefill.day),
                texts=FormTexts(amount=prefill.amount, comment=prefill.comment),
                instrument_id=prefill.instrument_id,
                # A rule buying a Bond Series buys the Series its type and the day give
                bond_mode=bond_type is not None,
                bond_type=bond_type or BondType.EDO,
                cash_currency=prefill.cash_currency,
            )
        edited = self.edited
        account_id = edited.account_id if edited else next(iter(self.accounts))
        texts = FormTexts.of(edited)
        bonds_account = self._accounts[account_id].account_type is AccountType.BONDS
        return FormState(
            account_id=account_id,
            kind=edited.transaction_type if edited else TransactionType.DEPOSIT,
            day=format_date(edited.date if edited else today),
            texts=texts,
            target_id=edited.target_account_id if edited else None,
            instrument_id=edited.instrument_id if edited else None,
            # A new Buy on a Bonds Account starts in the bond mode
            bond_mode=self.edited_series is not None or (edited is None and bonds_account),
            bond_type=self._own_type or BondType.EDO,
            rollover=self.edited_series is not None and edited is not None and edited.price != ISSUE_PRICE,
            direction=SELL_CURRENCY if edited is not None and edited.to_pln else BUY_CURRENCY,
            cash_currency=self._own_cash_currency,
            dividend_currency=self._own_dividend_currency,
            # Only on an Account with an FX Conversion Fee, unchecked unless the edited trade was converted (spec 3.3)
            convert=texts.charged != "",
        )

    def bond_mode_for(self, account_id: int) -> bool:
        """A new Buy follows the Account: the bond mode on a Bonds Account, else an Instrument."""
        return self._accounts[account_id].account_type is AccountType.BONDS

    # The choices the form derives from its state

    def bonds_chosen(self, state: FormState) -> bool:
        """A Buy in the bond mode: the type and date give the Instrument, a Bond Series in PLN."""
        return state.kind is TransactionType.BUY and state.bond_mode

    def redeems_bonds(self, state: FormState) -> bool:
        """A Sell of a Bond Series: an Early Redemption, which picks its Lot."""
        return state.kind is TransactionType.SELL and state.instrument_id in self._bond_ids

    def _interest(self, state: FormState) -> bool:
        """A Dividend without an Instrument is interest, e.g. on the Account's cash."""
        return state.kind is TransactionType.DIVIDEND and state.instrument_id is None

    def _settles(self, state: FormState) -> bool:
        """Paid from, or into, a Cash Currency the user may choose: a Buy, Sell or Dividend, interest aside."""
        return state.kind.settles_in_cash_currency and not self._interest(state)

    def _cash_currencies(self, state: FormState) -> tuple[str, ...]:
        return self._accounts[state.account_id].cash_currencies

    def _dividend_currency(self, state: FormState) -> Choice[str]:
        interest = self._interest(state)
        if not interest:
            own = self._own_dividend_currency
            return Choice(False, {own: own} if own else {}, state.dividend_currency)
        options = list(dict.fromkeys([*self._cash_currencies(state), *filter(None, [self._own_dividend_currency])]))
        chosen = state.dividend_currency if state.dividend_currency in options else PLN
        return Choice(True, {c: c for c in options}, chosen, "Waluta")

    def trade_currency(self, state: FormState) -> str:
        """The Instrument's currency; interest without one is in the currency the user chose."""
        if self.bonds_chosen(state):
            return PLN
        if state.instrument_id is not None:
            return self._instruments[state.instrument_id].quote_currency
        if state.kind is TransactionType.DIVIDEND:
            return self._dividend_currency(state).value or PLN
        return PLN

    def _default_settlement(self, state: FormState, currency: str) -> str:
        """The Instrument's own currency if the Account holds it, else PLN (spec 3.3).

        An edited trade keeps how it was paid while its Account and currency stay, even if the Account's Cash
        Currencies changed since.
        """
        edited = self.edited
        if (
            edited is not None
            and edited.transaction_type.settles_in_cash_currency
            and edited.account_id == state.account_id
            and edited.instrument_id is not None
            and self._instruments[edited.instrument_id].quote_currency == currency
        ):
            return edited.cash_currency
        return currency if currency in self._cash_currencies(state) else PLN

    def _paid_from(self, state: FormState) -> Choice[str]:
        """An Account holding the Instrument's currency pays from that cash or from PLN, as the user chooses; a
        Dividend goes into either the same way."""
        currency = self.trade_currency(state)
        sources = {currency: f"gotówka {currency}", PLN: "PLN z przewalutowaniem"}
        held = currency in self._cash_currencies(state)
        offered = held or self._default_settlement(state, currency) != PLN
        visible = self._settles(state) and currency != PLN and offered
        label = "Płatność" if state.kind.is_buy_or_sell else "Wpływ"
        if not visible:
            return Choice(False, {}, state.paid_from, label)
        chosen = state.paid_from if state.paid_from in sources else self._default_settlement(state, currency)
        return Choice(True, sources, chosen, label)

    def settlement_currency(self, state: FormState) -> str:
        """The Cash Currency a Buy or Sell is paid from, or a Dividend into: the user's choice where the Account
        offers one; interest goes into the cash of its own currency."""
        if self._interest(state):
            return self.trade_currency(state)
        paid_from = self._paid_from(state)
        return paid_from.value if paid_from.visible and paid_from.value else PLN

    def fee_percent(self, state: FormState) -> Decimal | None:
        """The Account's FX Conversion Fee; an edited converted trade keeps its own while its Account stays."""
        edited = self.edited
        if edited is not None and edited.account_id == state.account_id:
            own = edited.fx_conversion_fee_percent
            if own is not None:
                return own
        return self._accounts[state.account_id].fx_conversion_fee_percent

    def _convert_shown(self, state: FormState) -> bool:
        currency = self.trade_currency(state)
        settled_in = self.settlement_currency(state)
        return self._settles(state) and currency != PLN and settled_in == PLN and self.fee_percent(state) is not None

    def converted_by_broker(self, state: FormState) -> bool:
        return self._convert_shown(state) and state.convert

    def _cash_currency(self, state: FormState) -> Choice[str]:
        """A Deposit, Withdrawal or Cost on an Account holding a foreign currency may be in that cash."""
        options = list(dict.fromkeys([*self._cash_currencies(state), self._own_cash_currency]))
        visible = state.kind.moves_cash_amount and options != [PLN]
        chosen = state.cash_currency if state.cash_currency in options else PLN
        return Choice(visible, {c: c for c in options}, chosen, "Waluta")

    def cash_paid_in(self, state: FormState) -> str:
        """The Cash Currency of a Deposit, Withdrawal or Cost: PLN unless the user chose a foreign one."""
        choice = self._cash_currency(state)
        return choice.value if choice.visible and choice.value else PLN

    def _target(self, state: FormState) -> Choice[int]:
        others = {i: name for i, name in self.targets.items() if i != state.account_id}
        chosen = state.target_id if state.target_id in others else next(iter(others), None)
        return Choice(state.kind.is_transfer, others, chosen, "Na konto")

    def _target_id(self, state: FormState) -> int:
        target = self._target(state).value
        if target is None:
            raise FormError("target", "Wybierz konto docelowe.")
        return target

    def _exchange_currency(self, state: FormState) -> Choice[str]:
        foreign = [c for c in self._cash_currencies(state) if c != PLN]
        # Buying a currency the Account does not hold yet is the usual first exchange, so offer the common ones
        if state.direction == BUY_CURRENCY:
            foreign = [*foreign, *SUGGESTED_EXCHANGE_CURRENCIES]
        edited = self.edited
        if edited is not None and edited.transaction_type is TransactionType.CURRENCY_EXCHANGE:
            foreign = [*foreign, edited.cash_currency]
        foreign = [c for c in dict.fromkeys(foreign) if c != PLN]
        chosen = state.exchange_currency if state.exchange_currency in foreign else None
        if chosen is None and edited is not None and edited.cash_currency in foreign:
            chosen = edited.cash_currency
        return Choice(
            state.kind is TransactionType.CURRENCY_EXCHANGE,
            {c: c for c in foreign},
            chosen or (foreign[0] if foreign else None),
            "Waluta",
        )

    def held_lots(self, state: FormState) -> dict[int, Lot]:
        """The Lots of the chosen Bond Series the Account holds on the chosen day, by the Transaction that opened
        them; the edited Sell's own units count as held."""
        if state.instrument_id is None:
            return {}
        try:
            held = open_lots(
                self.context.transactions,  # in entry order, which settles same-day ties
                state.account_id,
                state.instrument_id,
                parse_date(state.day),
                edited_id=None if self.edited is None else self.edited.id,
            )
        except ValueError, TransactionError:
            return {}
        return {lot.opened_by: lot for lot in held if lot.opened_by is not None}

    def _lot(self, state: FormState, held_lots: Mapping[int, Lot] | None = None) -> Choice[int]:
        """An Early Redemption names the Lot it redeems (ADR-0007): the one chosen, else the edited Sell's own, else
        the oldest."""
        if not self.redeems_bonds(state):
            return Choice(False, {}, state.lot_id, "Partia")
        held_lots = self.held_lots(state) if held_lots is None else held_lots
        options = {
            lot_id: f"{format_date(held.date)} · {format_quantity(held.quantity)} szt. · "
            f"po {format_pln(held.cost / held.quantity)}"
            for lot_id, held in held_lots.items()
        }
        own = self.edited.lot_id if self.edited is not None else None
        chosen = state.lot_id if state.lot_id in options else own if own in options else None
        return Choice(True, options, chosen if chosen is not None else next(iter(options), None), "Partia")

    # Bond Series

    def date_series(self, state: FormState) -> str | None:
        """The Series the chosen type and purchase date give, ``None`` until the date reads as one."""
        try:
            day = parse_date(state.day)
        except ValueError:
            return None
        name = series_name(state.bond_type, day)
        # An edited Buy stays in its own Series while its type and the month of its date stay
        if name == self._own_name and self.edited_series is not None:
            name = self.edited_series
        return name

    def chosen_series(self, state: FormState) -> BondSeries | None:
        """The Bond Series picked, else the one the type and purchase date give."""
        name = state.series_pick or self.date_series(state)
        if name is None:
            return None
        return self.context.held_series.get(name) or BondSeries(None, name, self.context.mf_terms.get(name))

    def series_to_buy(self, state: FormState) -> str | None:
        """The name of the Bond Series a bond-mode Buy buys, ``None`` outside the bond mode."""
        if not self.bonds_chosen(state):
            return None
        series = self.chosen_series(state)
        if series is None:
            raise FormError("day", "Data musi mieć postać DD.MM.RRRR.")
        return series.name

    def _series_choice(self, state: FormState, series: BondSeries | None) -> Choice[str]:
        """The type's Series from the MF file, the newest first, with the chosen one even when MF lacks it."""
        kind = state.bond_type
        if kind not in self._type_series:
            sold = series_of_type(self.context.mf_terms.values(), kind)
            self._type_series[kind] = {t.series: f"{t.series} · sprzedaż {t.sale_start:%m.%Y}" for t in sold}
        options = self._type_series[kind]
        if series is not None and series.name not in options:
            options = {series.name: series.name, **options}
        return Choice(True, options, series.name if series else None, "Seria")

    def _series_text(self, state: FormState, series: BondSeries | None, rollover: bool) -> str:
        """The Series the bond mode buys, with its first rate, and whether the date is within its sale."""
        if series is None:
            return "Podaj datę zakupu, by wybrać serię."
        parts = [f"Seria {series.name}"]
        if series.first_rate is not None:
            parts.append(f"1. okres: {format_percent(series.first_rate * 100)}")
        if series.mf is None:
            parts.append("jeszcze nie ma jej w pliku MF")
        else:
            try:
                outside = not sold_on(series.mf, parse_date(state.day), rollover and state.rollover)
            except ValueError:
                outside = False
            if outside:
                window = f"{format_date(series.mf.sale_start)}–{format_date(series.mf.sale_end)}"
                parts.append(f"data zakupu poza sprzedażą serii ({window})")
        return " · ".join(parts)

    def bond_price(self, state: FormState) -> str | None:
        """The price of one bond the bond mode buys: 100 zł, or the Rollover price of the Series; ``None`` outside
        the bond mode or without a Series."""
        series = self.chosen_series(state)
        if not self.bonds_chosen(state) or series is None:
            return None
        rollover_price = series.rollover_price if state.rollover else None
        return format_exact(rollover_price or ISSUE_PRICE)

    # Early Redemption

    def _chosen_lot(self, state: FormState) -> Lot | None:
        """The Lot an Early Redemption redeems, ``None`` for any other Transaction."""
        if not self.redeems_bonds(state):
            return None
        held_lots = self.held_lots(state)
        chosen = self._lot(state, held_lots).value
        return None if chosen is None else held_lots.get(chosen)

    def lot_quantity(self, state: FormState) -> str | None:
        """The bonds of the Lot an Early Redemption picks, to prefill its quantity."""
        held = self._chosen_lot(state)
        return None if held is None else format_quantity(held.quantity)

    def redemption(self, state: FormState) -> EarlyRedemption | None:
        """The prefill of an Early Redemption of the quantity typed: one bond's gross value as the price, the fee as
        the commission and the tax the Account's Tax Regime withholds (spec 3.4.1); ``None`` while it cannot be
        valued."""
        held = self._chosen_lot(state)
        if held is None or state.instrument_id is None:
            return None
        try:
            price = self.context.bond_data.price(state.instrument_id, parse_date(state.day))
            units = parse_number(state.texts.quantity)
        except ValueError:
            return None  # a quantity or date that does not read yet
        tax_rate = tax_regime_for(self._accounts[state.account_id].account_type).withheld_tax_rate
        return None if price is None else early_redemption(price, held, units, tax_rate)

    def net_text(self, state: FormState) -> str:
        """A Dividend's gross amount less its withholding tax, or what an Early Redemption pays out, once the amounts
        read as numbers."""
        texts = state.texts
        try:
            if self.redeems_bonds(state):
                paid = parse_number(texts.quantity) * parse_number(texts.price)
                deducted = [parse_number(t) for t in (texts.commission, texts.withholding_tax) if t.strip()]
                return f"Wypłata netto: {format_pln(paid - sum(deducted, Decimal(0)))}"
            tax_text = texts.withholding_tax.strip()
            value = parse_number(texts.gross) - (parse_number(tax_text) if tax_text else Decimal(0))
        except ValueError:
            return ""
        return f"Netto: {format_amount(value, self.trade_currency(state))}"

    # The layout

    def layout(self, state: FormState) -> FormLayout:
        """The fields the chosen type needs; the price is in the Instrument's currency, a foreign one also takes a
        rate, and an Account holding that currency pays from it (spec 3.3, 3.5)."""
        kind = state.kind
        trade, dividend_type, units_only = kind.is_buy_or_sell, kind.is_dividend, not kind.has_amount
        currency = self.trade_currency(state)
        unit = currency_unit(currency)
        bonds = self.bonds_chosen(state)
        series = self.chosen_series(state) if bonds else None
        rollover = series is not None and series.rollover_price is not None
        redemption = self.redeems_bonds(state)
        converted = self.converted_by_broker(state)
        settled_in = self.settlement_currency(state)
        fee = self.fee_percent(state)
        convert_text = ""
        if fee is not None:
            account = self._accounts[state.account_id]
            convert_text = f"Prowizja {account.broker or account.name} (przewalutowanie {format_percent(fee)})"
        exchange_currency = self._exchange_currency(state)
        shown = exchange_currency.value or "waluta"
        paid_in = self.cash_paid_in(state)
        # A foreign Deposit or Withdrawal takes a rate of the user's too; a foreign Cost counts at the NBP Rate
        flow_rate = kind in (TransactionType.DEPOSIT, TransactionType.WITHDRAWAL) and paid_in != PLN
        return FormLayout(
            amount=Shown(not trade and not dividend_type and not units_only, f"Kwota ({currency_unit(paid_in)})"),
            instrument_fields=trade or dividend_type or units_only,
            target=self._target(state),
            ratio=kind is TransactionType.SPLIT,
            exchange_fields=kind is TransactionType.CURRENCY_EXCHANGE,
            direction=Choice(
                True,
                {BUY_CURRENCY: f"PLN → {shown}", SELL_CURRENCY: f"{shown} → PLN"},
                state.direction,
                "Kierunek",
            ),
            exchange_currency=exchange_currency,
            foreign_amount=Shown(True, f"Kwota ({shown})"),
            cash_currency=self._cash_currency(state),
            dividend_currency=self._dividend_currency(state),
            quantity=Shown(
                trade or kind in (TransactionType.DRIP, TransactionType.SECURITY_TRANSFER),
                "Liczba obligacji" if bonds else "Liczba",
            ),
            bond_mode=kind is TransactionType.BUY,
            bond_fields=bonds,
            series=self._series_choice(state, series) if bonds else Choice(False),
            series_text=self._series_text(state, series, rollover) if bonds else "",
            rollover=rollover,
            instrument=not bonds,
            lot=self._lot(state),
            price=Shown(trade, f"Cena ({unit})"),
            commission=trade,
            gross=Shown(dividend_type, f"Kwota brutto ({unit})"),
            withholding_tax=Shown(
                dividend_type or redemption, f"{'Podatek pobrany' if redemption else 'Podatek u źródła'} ({unit})"
            ),
            net=Shown(dividend_type or redemption, self.net_text(state)),
            paid_from=self._paid_from(state),
            # Interest paid into foreign cash takes a rate too: it values that cash in PLN, like a Buy paid from it; a
            # DRIP converts nothing, so it counts at the NBP Rate
            fx_rate=Shown(
                flow_rate or ((trade or kind is TransactionType.DIVIDEND) and currency != PLN and not converted),
                f"Kurs {paid_in if flow_rate else currency}/PLN",
                "Puste = kurs NBP z dnia roboczego przed datą",
            ),
            convert=Shown(self._convert_shown(state), convert_text),
            charged=Shown(
                converted,
                *(
                    ("Kwota pobrana przez brokera (zł)", "Za liczbę × cenę, bez prowizji")
                    if trade
                    else ("Kwota wypłacona przez brokera (zł)", "Za kwotę netto")
                ),
            ),
            # Only a new Buy: an automatic Exchange is a Transaction of its own once saved
            auto_exchange=self.edited is None and kind is TransactionType.BUY and settled_in != PLN,
            spend=Shown(kind is TransactionType.BUY, f"Kwota do wydania ({currency_unit(settled_in)})"),
        )

    # The quantity proposed from the amount to spend (#120)

    def proposed_quantity(self, state: FormState) -> str | None:
        """The units a Buy's amount to spend buys: the amount (less the commission when both are PLN) at the rate it
        is paid at, divided by the price and rounded down to the Instrument's decimal places. ``None`` until the
        amount and price read, without the NBP Rate, or when it buys nothing."""
        if state.kind is not TransactionType.BUY:
            return None
        texts = state.texts
        try:
            amount = parse_number(texts.spend)
            price = parse_number(texts.price)
            commission = parse_number(texts.commission) if texts.commission.strip() else Decimal(0)
            rate = self._spend_rate(state)
        except ValueError, MissingNbpRateError:
            return None
        if self.settlement_currency(state) == PLN:
            amount -= commission  # paid from PLN like the amount; from foreign cash, the commission is apart
        if not (amount > 0 and price > 0 and rate > 0):
            return None
        instrument = None if self.bonds_chosen(state) or state.instrument_id is None else state.instrument_id
        decimals = 0 if instrument is None else self._instruments[instrument].quantity_decimals
        units = (amount / rate / price).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN)
        return format_quantity(units) if units > 0 else None

    def _spend_rate(self, state: FormState) -> Decimal:
        """PLN per unit of the Instrument's currency the amount to spend converts at: 1 when no conversion is needed;
        the NBP Rate raised by the FX Conversion Fee when the broker converts; else the user's rate or the NBP Rate."""
        currency = self.trade_currency(state)
        if currency == PLN or self.settlement_currency(state) != PLN:
            return Decimal(1)
        own = state.texts.fx_rate.strip()
        if own and not self.converted_by_broker(state):
            return parse_number(own)
        nbp = self._rate(currency, parse_date(state.day)).rate
        fee = self.fee_percent(state) if self.converted_by_broker(state) else None
        return nbp if fee is None else nbp * (1 + fee / 100)

    def with_exchange(self, state: FormState) -> bool:
        """Whether the save adds the Exchange that buys the Buy's foreign cash first (spec 3.3)."""
        return self.layout(state).auto_exchange and state.auto_exchange

    # The draft

    def _rate(self, currency: str, day: date) -> NbpRate:
        """The edited Transaction's own NBP Rate while its currency and date stay, so editing works offline.

        Otherwise it is fetched (or read from the cache) only now, so a missing one blocks the save (spec 3.3).
        """
        edited = self.edited
        if edited is not None and edited.date == day:
            own = edited.nbp_rate
            if own is not None and own.currency == currency:
                return own
        return self.context.rates(currency, day)

    def _broker_conversion(self, state: FormState) -> BrokerConversion | None:
        """What the broker charged (or, for a Dividend, credited) when the user marked its conversion (spec 3.3)."""
        if not self.converted_by_broker(state):
            return None
        if not state.texts.charged.strip():
            done = "pobraną" if state.kind.is_buy_or_sell else "wypłaconą"
            raise FormError("charged", f"Podaj kwotę {done} przez brokera.")
        fee = self.fee_percent(state)
        assert fee is not None  # the checkbox shows only with a fee
        charged = _read(parse_number, state.texts.charged, "charged", "Kwota od brokera musi być liczbą, np. 5 451,90.")
        return BrokerConversion(charged, fee)

    def draft(self, state: FormState, series_id: int | None = None) -> TransactionDraft:
        """The Transaction the form describes; a bond-mode Buy buys the Series ``series_id``. Raises FormError for a
        field that does not read, TransactionError for one the Transaction refuses and MissingNbpRateError."""
        kind = state.kind
        texts = state.texts
        account = state.account_id
        day = _read(parse_date, state.day, "day", "Data musi mieć postać DD.MM.RRRR.")
        if kind is TransactionType.CURRENCY_EXCHANGE:
            currency = self._exchange_currency(state).value
            if currency is None:
                raise TransactionError("To konto nie ma waluty obcej. Dodaj ją w Ustawieniach, w Kontach.")
            return currency_exchange(
                account,
                day,
                currency,
                _read(parse_number, texts.foreign_amount, "foreign_amount", FOREIGN_AMOUNT_MESSAGE),
                _read(parse_number, texts.amount, "amount", AMOUNT_MESSAGE),
                to_pln=state.direction == SELL_CURRENCY,
                comment=texts.comment,
            )
        if kind.is_dividend:
            return self._dividend(state, day)
        if kind is TransactionType.CASH_TRANSFER:
            value = _read(parse_number, texts.amount, "amount", AMOUNT_MESSAGE)
            return cash_transfer(account, day, self._target_id(state), value, texts.comment)
        if not kind.has_amount:
            return self._units_only(state, day)
        if not kind.is_buy_or_sell:
            value = _read(parse_number, texts.amount, "amount", AMOUNT_MESSAGE)
            paid_in = self.cash_paid_in(state)
            if paid_in == PLN:
                return TransactionDraft(account, day, kind, value, texts.comment)
            nbp = self._rate(paid_in, day)
            if kind is TransactionType.COST:
                return cost(account, day, value, texts.comment, cash_currency=paid_in, nbp_rate=nbp)
            own_rate = texts.fx_rate.strip()
            rate = _read(parse_number, own_rate, "fx_rate", RATE_MESSAGE) if own_rate else None
            return deposit_or_withdrawal(
                account, day, kind, value, texts.comment, cash_currency=paid_in, fx_rate=rate, nbp_rate=nbp
            )
        bought = state.instrument_id if series_id is None else series_id
        if bought is None:
            raise FormError("instrument", INSTRUMENT_MESSAGE)
        currency = self.trade_currency(state)
        nbp_rate = None if currency == PLN else self._rate(currency, day)
        conversion = self._broker_conversion(state)
        own_rate = texts.fx_rate.strip() if nbp_rate and conversion is None else ""
        redemption = self.redeems_bonds(state)
        tax_text = texts.withholding_tax.strip() if redemption else ""
        return buy_or_sell(
            account,
            day,
            kind,
            bought,
            _read(parse_number, texts.quantity, "quantity", QUANTITY_MESSAGE),
            _read(parse_number, texts.price, "price", "Cena musi być liczbą, np. 45,50."),
            _read(parse_number, texts.commission, "commission", "Prowizja musi być liczbą, np. 5,00.")
            if texts.commission.strip()
            else Decimal(0),
            texts.comment,
            fx_rate=_read(parse_number, own_rate, "fx_rate", RATE_MESSAGE) if own_rate else None,
            nbp_rate=nbp_rate,
            cash_currency=self.settlement_currency(state),
            conversion=conversion,
            withholding_tax=_read(parse_number, tax_text, "withholding_tax", TAX_MESSAGE) if tax_text else Decimal(0),
            lot_id=self._lot(state).value if redemption else None,
        )

    def _units_only(self, state: FormState, day: date) -> TransactionDraft:
        """A Split, or a Security Transfer of some units to the target Account."""
        instrument, texts = state.instrument_id, state.texts
        if instrument is None:
            raise FormError("instrument", INSTRUMENT_MESSAGE)
        if state.kind is TransactionType.SPLIT:
            message = "Podaj split w postaci X:Y z liczb całkowitych, np. 2:1."
            new, old = _read(parse_ratio, texts.ratio, "ratio", message)
            return split(state.account_id, day, instrument, SplitRatio(new, old), texts.comment)
        units = _read(parse_number, texts.quantity, "quantity", QUANTITY_MESSAGE)
        target = self._target_id(state)
        return security_transfer(state.account_id, day, target, instrument, units, texts.comment)

    def _dividend(self, state: FormState, day: date) -> TransactionDraft:
        """A Dividend, interest or DRIP; a foreign-currency one takes the NBP Rate and maybe the user's rate or, for a
        Dividend, the amount the broker credited."""
        texts = state.texts
        gross = _read(parse_number, texts.gross, "gross", "Kwota brutto musi być liczbą, np. 100,50.")
        tax_text = texts.withholding_tax.strip()
        message = TAX_MESSAGE
        tax = _read(parse_number, tax_text, "withholding_tax", message) if tax_text else Decimal(0)
        currency = self.trade_currency(state)
        nbp_rate = None if currency == PLN else self._rate(currency, day)
        conversion = self._broker_conversion(state)
        own_rate = texts.fx_rate.strip() if nbp_rate and conversion is None else ""
        rate = _read(parse_number, own_rate, "fx_rate", RATE_MESSAGE) if own_rate else None
        instrument = state.instrument_id
        if state.kind is TransactionType.DIVIDEND:
            # Interest edited as interest keeps naming the Lot whose coupon it is, so its Draft stays confirmed
            edited = self.edited
            was_interest = edited is not None and edited.transaction_type is TransactionType.DIVIDEND
            coupon_lot = edited.lot_id if edited is not None and was_interest else None
            return dividend(
                state.account_id,
                day,
                gross,
                tax,
                texts.comment,
                instrument_id=instrument,
                fx_rate=rate,
                nbp_rate=nbp_rate,
                cash_currency=self.settlement_currency(state),
                conversion=conversion,
                lot_id=coupon_lot if instrument is None else None,
            )
        if instrument is None:
            raise FormError("instrument", INSTRUMENT_MESSAGE)
        units = _read(parse_number, texts.quantity, "quantity", QUANTITY_MESSAGE)
        return drip(state.account_id, day, instrument, units, gross, tax, texts.comment, nbp_rate=nbp_rate)


def _read[T](parse: Callable[[str], T], text: str, field: str, message: str) -> T:
    """Parse a form field, turning a parse failure into the field's FormError with ``message``."""
    try:
        return parse(text or "")
    except ValueError:
        raise FormError(field, message) from None
