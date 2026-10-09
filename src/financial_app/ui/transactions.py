"""The Transakcje tab and the transaction dialog for adding, editing and deleting (spec 3.3).

For now: PLN Deposits and Withdrawals, Currency Exchanges, and Buys and Sells: foreign-currency ones paid from foreign
cash or in PLN, converted at the user's rate, the NBP Rate (D-1) or by the broker for its FX Conversion Fee.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.currencies import MissingNbpRateError, NbpRate
from financial_app.domain.formatting import (
    currency_unit,
    format_amount,
    format_date,
    format_exact,
    format_percent,
    format_pln,
    format_quantity,
    format_rate,
    format_unit_price,
    parse_date,
    parse_number,
)
from financial_app.domain.transactions import (
    PLN,
    BrokerConversion,
    Transaction,
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    covering_exchange,
    currency_exchange,
    lowest_cash_balance,
)
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import (
    add_transactions,
    delete_transaction,
    list_transactions,
    update_transaction,
)
from financial_app.sources.nbp import NbpRates

# Currency Exchange directions in the dialog: buying the foreign currency for PLN, or selling it for PLN
_BUY, _SELL = "buy", "sell"
TRANSACTION_TYPE_OPTIONS = {transaction_type.value: transaction_type.label for transaction_type in TransactionType}
COLUMNS = "grid-template-columns: 7rem minmax(8rem, 1fr) 6rem minmax(9rem, 1fr) 9rem minmax(8rem, 2fr)"


@dataclass
class TransactionsPage:
    """The Transakcje tab; clicking a Transaction opens it for editing or deleting."""

    engine: Engine
    rates: NbpRates

    def refresh(self) -> None:
        """Redraw the list if it is on screen (e.g. after a save)."""
        self.rows.refresh()

    def build(self) -> None:
        ui.label("Transakcje").classes("text-2xl font-bold")
        # The marker sits outside the refreshable list so it survives a refresh
        with ui.column().classes("w-full max-w-6xl gap-0").mark("transactions"):
            self.rows()

    @ui.refreshable_method
    def rows(self) -> None:
        transactions = list_transactions(self.engine)
        if not transactions:
            ui.label("Brak transakcji. Dodaj pierwszą przyciskiem „+”.").classes("text-gray-500")
            return
        account_names = {account.id: account.name for account in list_accounts(self.engine)}
        instruments = {instrument.id: instrument for instrument in list_instruments(self.engine)}
        with ui.element("div").classes("grid w-full gap-x-4 border-b py-1 font-medium").style(COLUMNS):
            for header in ("Data", "Konto", "Typ", "Instrument", "Kwota", "Komentarz"):
                ui.label(header)
        for transaction in transactions:
            row = ui.element("div").classes("grid w-full gap-x-4 border-b py-1 cursor-pointer hover:bg-gray-100")
            row.style(COLUMNS).mark("transaction-row")
            # Only this tab is on screen, so it is the only one to redraw after an edit
            row.on("click", lambda t=transaction: open_transaction_dialog(self.engine, self.rates, self.refresh, t))
            with row:
                ui.label(format_date(transaction.date))
                ui.label(account_names[transaction.account_id])
                ui.label(transaction.transaction_type.label)
                with ui.column().classes("gap-0"):
                    if transaction.transaction_type is TransactionType.CURRENCY_EXCHANGE:
                        _exchange_cell(transaction)
                    if transaction.instrument_id is not None:
                        assert transaction.quantity is not None and transaction.price is not None
                        instrument = instruments[transaction.instrument_id]
                        ui.label(instrument.name)
                        price = format_unit_price(transaction.price, instrument.quote_currency)
                        ui.label(f"{format_quantity(transaction.quantity)} × {price}").classes("text-xs text-gray-500")
                        if transaction.nbp_rate is not None:
                            ui.label(_rates_text(transaction)).classes("text-xs text-gray-500")
                with ui.column().classes("gap-0 items-end"):
                    if transaction.is_paid_in_foreign_cash:
                        currency = transaction.cash_currency
                        ui.label(format_amount(transaction.foreign_cash_change, currency, signed=True))
                        actual = format_pln(transaction.actual_cash_change, signed=True)
                        ui.label(f"rzeczywista {actual}").classes("text-xs text-gray-500")
                    else:
                        ui.label(format_pln(transaction.cash_change, signed=True))
                    if transaction.tax_amount != transaction.actual_amount:
                        tax = format_pln(transaction.tax_cash_change, signed=True)
                        ui.label(f"podatkowa {tax}").classes("text-xs text-gray-500")
                ui.label(transaction.comment).classes("text-gray-600")


def _exchange_cell(exchange: Transaction) -> None:
    """Which way the currency went, how much and at what rate (PLN per unit)."""
    currency = exchange.cash_currency
    ui.label(f"{currency} → PLN" if exchange.to_pln else f"PLN → {currency}")
    assert exchange.quantity is not None
    rate = format_rate(exchange.actual_amount / exchange.quantity)
    amount = format_amount(exchange.foreign_cash_change, currency, signed=True)
    ui.label(f"{amount} po {rate}").classes("text-xs text-gray-500")


def open_transaction_dialog(
    engine: Engine, rates: NbpRates, on_saved: Callable[[], None], transaction: Transaction | None = None
) -> None:
    """Open a fresh dialog for a new Transaction (``None``) or for editing or deleting ``transaction``.

    It is built on demand and removed when closed; ``on_saved`` runs after a save or a delete.
    """
    dialog = ui.dialog()
    dialog.on("hide", dialog.delete)
    all_accounts = list_accounts(engine)
    account_names = {a.id: a.name for a in all_accounts}
    # Deposits, Withdrawals and commissions are in PLN so far, so only Accounts holding PLN can take part;
    # an edited Transaction keeps offering its own Account even if that has been deactivated since
    accounts = {
        a.id: a.name
        for a in all_accounts
        if (a.active and PLN in a.cash_currencies) or (transaction is not None and a.id == transaction.account_id)
    }
    cash_currencies = {a.id: a.cash_currencies for a in all_accounts}
    accounts_by_id = {a.id: a for a in all_accounts}
    all_instruments = list_instruments(engine)
    instruments = {i.id: i.name for i in all_instruments}
    currencies = {i.id: i.quote_currency for i in all_instruments}
    with dialog, ui.card().classes("w-[460px]"):
        ui.label("Nowa transakcja" if transaction is None else "Edytuj transakcję").classes("text-lg font-bold")
        if not accounts:
            ui.label("Najpierw dodaj konto z walutą PLN w zakładce Ustawienia.").classes("text-gray-500")
            with ui.row().classes("w-full justify-end"):
                ui.button("Zamknij", on_click=dialog.close).props("flat")
            dialog.open()
            return

        kind = transaction.transaction_type if transaction else TransactionType.DEPOSIT
        transaction_type = ui.select(TRANSACTION_TYPE_OPTIONS, label="Typ", value=kind.value)
        transaction_type.classes("w-full").mark("transaction-type")
        account_id = transaction.account_id if transaction else next(iter(accounts))
        account = ui.select(accounts, label="Konto", value=account_id).classes("w-full")
        account.mark("transaction-account")
        day_text = format_date(transaction.date if transaction else date.today())
        day = ui.input("Data", value=day_text).classes("w-full").mark("transaction-date")
        with day.add_slot("append"):
            icon = ui.icon("event").classes("cursor-pointer")
            with ui.menu() as menu:
                ui.date(mask="DD.MM.YYYY").bind_value(day).on_value_change(menu.close)
            icon.on("click", menu.open)

        texts = _field_texts(transaction)
        with ui.column().classes("w-full gap-0") as exchange_fields:
            sells = transaction is not None and transaction.to_pln
            directions = {_BUY: "PLN → waluta", _SELL: "waluta → PLN"}
            direction = ui.select(directions, label="Kierunek", value=_SELL if sells else _BUY).classes("w-full")
            direction.mark("transaction-direction")
            exchange_currency = ui.select([], label="Waluta").classes("w-full").mark("transaction-currency")
            foreign_amount = ui.input(value=texts.foreign_amount).classes("w-full")
            foreign_amount.mark("transaction-foreign-amount")
        amount = ui.input("Kwota (zł)", value=texts.amount).classes("w-full").mark("transaction-amount")
        with ui.column().classes("w-full gap-0") as trade_fields:
            instrument_id = transaction.instrument_id if transaction else None
            instrument = ui.select(instruments, label="Instrument", value=instrument_id).classes("w-full")
            instrument.mark("transaction-instrument")
            if not instruments:
                ui.label("Najpierw dodaj instrument w zakładce Ustawienia.").classes("text-gray-500")
            quantity = ui.input("Liczba", value=texts.quantity).classes("w-full").mark("transaction-quantity")
            price = ui.input("Cena (zł)", value=texts.price).classes("w-full").mark("transaction-price")
            paid_from = ui.select({}, label="Płatność").classes("w-full").mark("transaction-paid-from")
            fx_rate = ui.input(value=texts.fx_rate).props('hint="Puste = kurs NBP z dnia roboczego przed datą"')
            fx_rate.classes("w-full").mark("transaction-fx-rate")
            commission = ui.input("Prowizja (zł)", value=texts.commission).classes("w-full")
            commission.mark("transaction-commission")
            # Only on an Account with an FX Conversion Fee, unchecked unless the edited trade was converted (spec 3.3)
            convert = ui.checkbox(value=texts.charged != "").mark("transaction-conversion")
            charged = ui.input("Kwota pobrana przez brokera (zł)", value=texts.charged).classes("w-full")
            charged.props('hint="Za liczbę × cenę, bez prowizji"').mark("transaction-charged")
            # Only a new Buy: an automatic Exchange is a Transaction of its own once saved
            auto_exchange = ui.checkbox("Wymień walutę automatycznie").mark("transaction-auto-exchange")

        def default_settlement(currency: str) -> str:
            """The Instrument's own currency if the Account holds it, else PLN (spec 3.3).

            An edited trade keeps how it was paid while its Account and currency stay, even if the Account's Cash
            Currencies changed since.
            """
            if (
                transaction is not None
                and transaction.transaction_type.is_buy_or_sell
                and transaction.account_id == account.value
                and transaction.instrument_id is not None
                and currencies.get(transaction.instrument_id) == currency
            ):
                return transaction.cash_currency
            return currency if currency in cash_currencies.get(account.value, ()) else PLN

        def settlement_currency() -> str:
            """The Cash Currency a Buy or Sell is paid from: the user's choice where the Account offers one."""
            return paid_from.value if paid_from.visible and paid_from.value else PLN

        def fee_percent() -> Decimal | None:
            """The Account's FX Conversion Fee; an edited converted trade keeps its own while its Account stays."""
            if transaction is not None and transaction.account_id == account.value:
                own = transaction.fx_conversion_fee_percent
                if own is not None:
                    return own
            return accounts_by_id[account.value].fx_conversion_fee_percent

        def converted_by_broker() -> bool:
            return convert.visible and bool(convert.value)

        def update() -> None:
            """Show the fields the chosen type needs; the price is in the Instrument's currency, a foreign one also
            takes a rate, and an Account holding that currency pays from it (spec 3.3, 3.5)."""
            kind = TransactionType(transaction_type.value)
            amount.visible = not kind.is_buy_or_sell
            trade_fields.visible = kind.is_buy_or_sell
            exchange_fields.visible = kind is TransactionType.CURRENCY_EXCHANGE
            currency = currencies.get(instrument.value, PLN)
            price.props(f'label="Cena ({currency_unit(currency)})"')
            fx_rate.props(f'label="Kurs {currency}/PLN"')
            # An Account holding the Instrument's currency pays from that cash or from PLN, as the user chooses
            sources = {currency: f"gotówka {currency}", PLN: "PLN z przewalutowaniem"}
            held = currency in cash_currencies.get(account.value, ())
            paid_from.visible = currency != PLN and (held or default_settlement(currency) != PLN)
            if paid_from.visible:
                chosen_source = paid_from.value if paid_from.value in sources else default_settlement(currency)
                paid_from.set_options(sources, value=chosen_source)
            settled_in = settlement_currency()
            fee = fee_percent()
            convert.visible = currency != PLN and settled_in == PLN and fee is not None
            if fee is not None:
                chosen_account = accounts_by_id[account.value]
                broker = chosen_account.broker or chosen_account.name
                convert.text = f"Prowizja {broker} (przewalutowanie {format_percent(fee)})"
            charged.visible = converted_by_broker()
            fx_rate.visible = currency != PLN and not charged.visible
            auto_exchange.visible = transaction is None and kind is TransactionType.BUY and settled_in != PLN
            foreign = [c for c in cash_currencies.get(account.value, ()) if c != PLN]
            if transaction is not None and transaction.transaction_type is TransactionType.CURRENCY_EXCHANGE:
                foreign = list(dict.fromkeys([*foreign, transaction.cash_currency]))
            chosen = exchange_currency.value if exchange_currency.value in foreign else None
            if chosen is None and transaction is not None and transaction.cash_currency in foreign:
                chosen = transaction.cash_currency
            exchange_currency.set_options(foreign, value=chosen or (foreign[0] if foreign else None))
            shown = exchange_currency.value or "waluta"
            direction.set_options({_BUY: f"PLN → {shown}", _SELL: f"{shown} → PLN"}, value=direction.value)
            foreign_amount.props(f'label="Kwota ({shown})"')

        update()
        for field in (transaction_type, account, instrument, exchange_currency, paid_from, convert):
            field.on_value_change(update)
        comment = ui.input("Komentarz", value=transaction.comment if transaction else "").classes("w-full")
        comment.mark("transaction-comment")
        error = ui.label().classes("text-negative").mark("transaction-error")

        def stored_nbp_rate(currency: str, day_value: date) -> NbpRate:
            """The edited Transaction's own NBP Rate while its currency and date stay, so editing works offline.

            Otherwise it is fetched (or read from the cache) only now, so a missing one blocks the save (spec 3.3).
            """
            if transaction is not None and transaction.date == day_value:
                own = transaction.nbp_rate
                if own is not None and own.currency == currency:
                    return own
            return rates.before(currency, day_value)

        def read_draft() -> TransactionDraft:
            kind = TransactionType(transaction_type.value)
            day_value = _read(parse_date, day.value, "Data musi mieć postać DD.MM.RRRR.")
            if kind is TransactionType.CURRENCY_EXCHANGE:
                if exchange_currency.value is None:
                    raise TransactionError("To konto nie ma waluty obcej. Dodaj ją w Ustawieniach, w Kontach.")
                return currency_exchange(
                    account.value,
                    day_value,
                    exchange_currency.value,
                    _read(parse_number, foreign_amount.value, "Kwota w walucie musi być liczbą, np. 1 000,50."),
                    _read(parse_number, amount.value, "Kwota musi być liczbą, np. 1 000,50."),
                    to_pln=direction.value == _SELL,
                    comment=comment.value,
                )
            if not kind.is_buy_or_sell:
                value = _read(parse_number, amount.value, "Kwota musi być liczbą, np. 1 000,50.")
                return TransactionDraft(account.value, day_value, kind, value, comment.value)
            if instrument.value is None:
                raise TransactionError("Wybierz instrument.")
            currency = currencies[instrument.value]
            nbp_rate = None if currency == PLN else stored_nbp_rate(currency, day_value)
            conversion = None
            if converted_by_broker():
                if not charged.value.strip():
                    raise TransactionError("Podaj kwotę pobraną przez brokera.")
                fee = fee_percent()
                assert fee is not None  # the checkbox shows only with a fee
                charged_amount = _read(parse_number, charged.value, "Kwota pobrana musi być liczbą, np. 5 451,90.")
                conversion = BrokerConversion(charged_amount, fee)
            own_rate = fx_rate.value.strip() if nbp_rate and conversion is None else ""
            return buy_or_sell(
                account.value,
                day_value,
                kind,
                instrument.value,
                _read(parse_number, quantity.value, "Liczba musi być liczbą, np. 10 lub 0,5."),
                _read(parse_number, price.value, "Cena musi być liczbą, np. 45,50."),
                _read(parse_number, commission.value, "Prowizja musi być liczbą, np. 5,00.")
                if commission.value.strip()
                else Decimal(0),
                comment.value,
                fx_rate=_read(parse_number, own_rate, "Kurs musi być liczbą, np. 3,65.") if own_rate else None,
                nbp_rate=nbp_rate,
                cash_currency=settlement_currency(),
                conversion=conversion,
            )

        def save() -> None:
            try:
                draft = read_draft()
                if transaction is None:
                    # The Exchange goes first, so the Buy spends the cash it brings (spec 3.3)
                    exchange = [covering_exchange(draft)] if auto_exchange.visible and auto_exchange.value else []
                    add_transactions(engine, [*exchange, draft])
                else:
                    update_transaction(engine, transaction.id, draft)
            except (TransactionError, MissingNbpRateError) as exc:
                error.text = str(exc)
                return
            dialog.close()
            # An edit may move the Transaction to another day or Account, so also check where it was
            _warn_if_cash_runs_out(engine, "Zapisano", account_names, draft, transaction)
            on_saved()

        def delete(confirmation: ui.dialog) -> None:
            assert transaction is not None
            confirmation.close()
            try:
                delete_transaction(engine, transaction.id)
            except TransactionError as exc:
                error.text = f"Nie można usunąć tej transakcji. {exc}"
                return
            dialog.close()
            _warn_if_cash_runs_out(engine, "Usunięto", account_names, transaction)
            on_saved()

        with ui.row().classes("w-full items-center"):
            if transaction is not None:
                delete_button = ui.button("Usuń", on_click=lambda: _confirm_delete(delete))
                delete_button.props("flat color=negative").mark("delete-transaction")
            ui.space()
            ui.button("Anuluj", on_click=dialog.close).props("flat")
            ui.button("Zapisz" if transaction is None else "Zapisz zmiany", on_click=save)
    dialog.open()


def _confirm_delete(delete: Callable[[ui.dialog], None]) -> None:
    """Ask before deleting; ``delete`` gets the confirmation dialog so that it can close it."""
    confirmation = ui.dialog()
    confirmation.on("hide", confirmation.delete)
    with confirmation, ui.card():
        ui.label("Usunąć tę transakcję?").classes("text-lg font-bold")
        ui.label("Partie i salda zostaną przeliczone bez niej.").classes("text-gray-600")
        with ui.row().classes("w-full justify-end"):
            ui.button("Anuluj", on_click=confirmation.close).props("flat").mark("cancel-delete")
            ui.button("Usuń", on_click=lambda: delete(confirmation)).props("color=negative").mark("confirm-delete")
    confirmation.open()


@dataclass(frozen=True)
class _FieldTexts:
    amount: str = ""
    foreign_amount: str = ""
    quantity: str = ""
    price: str = ""
    fx_rate: str = ""
    commission: str = ""
    charged: str = ""


def _field_texts(transaction: Transaction | None) -> _FieldTexts:
    """The edit-field texts for ``transaction``, exact so that re-saving never rounds a value."""
    if transaction is None:
        return _FieldTexts()
    if transaction.transaction_type is TransactionType.CURRENCY_EXCHANGE:
        assert transaction.quantity is not None
        return _FieldTexts(
            amount=format_exact(transaction.actual_amount), foreign_amount=format_exact(transaction.quantity)
        )
    if not transaction.transaction_type.is_buy_or_sell:
        return _FieldTexts(amount=format_exact(transaction.actual_amount))
    assert transaction.quantity is not None and transaction.price is not None
    converted = transaction.fx_conversion_fee_percent is not None
    return _FieldTexts(
        quantity=format_quantity(transaction.quantity),
        price=format_exact(transaction.price),
        fx_rate="" if transaction.fx_rate is None else format_exact(transaction.fx_rate),
        commission=format_exact(transaction.commission),
        # What the broker charged for quantity × price, the commission aside
        charged=format_exact(transaction.converted_amount) if converted else "",
    )


def _rates_text(trade: Transaction) -> str:
    """The rate the trade was converted at, if not the NBP Rate, then the NBP Rate with its table and publication day.

    A broker-converted trade shows its effective rate and FX Conversion Fee.
    """
    nbp_rate = trade.nbp_rate
    assert nbp_rate is not None
    nbp = f"NBP {format_exact(nbp_rate.rate)} ({nbp_rate.table} z {format_date(nbp_rate.published_on)})"
    fee = trade.fx_conversion_fee
    if fee is not None:
        return f"kurs {format_rate(trade.effective_fx_rate)} · przewalutowanie {format_pln(fee)} · {nbp}"
    return nbp if trade.fx_rate is None else f"kurs {format_exact(trade.fx_rate)} · {nbp}"


def _warn_if_cash_runs_out(
    engine: Engine, done: str, account_names: dict[int, str], *touched: TransactionDraft | None
) -> None:
    """Warn per Account and Cash Currency whose Cash Balance goes negative from the earliest ``touched`` date on.

    Insufficient cash only warns (spec 3.3), so history can be entered in any order. ``done`` opens the
    message ("Zapisano", "Usunięto").
    """
    starts: dict[tuple[int, str], date] = {}
    for t in touched:
        if t is not None:
            for currency in dict.fromkeys((PLN, t.cash_currency)):
                key = (t.account_id, currency)
                starts[key] = min(t.date, starts.get(key, t.date))
    transactions = list_transactions(engine)
    for (account_id, currency), start in starts.items():
        lowest = lowest_cash_balance(transactions, account_id, start=start, currency=currency)
        if lowest < 0:
            cash = "Saldo gotówki" if currency == PLN else f"Saldo gotówki {currency}"
            ui.notify(
                f"{done}, ale {cash} konta {account_names[account_id]} jest ujemne: {format_amount(lowest, currency)}.",
                type="warning",
            )


def _read[T](parse: Callable[[str], T], text: str, message: str) -> T:
    """Parse a form field, turning a parse failure into a TransactionError with ``message``."""
    try:
        return parse(text)
    except ValueError:
        raise TransactionError(message) from None
