"""The Transakcje tab and the transaction dialog for adding, editing and deleting (spec 3.3).

For now: PLN Deposits and Withdrawals, and Buys and Sells paid in PLN, foreign-currency ones at the NBP Rate (D-1).
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
    format_date,
    format_exact,
    format_pln,
    format_quantity,
    format_unit_price,
    parse_date,
    parse_number,
)
from financial_app.domain.transactions import (
    Transaction,
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    lowest_cash_balance,
)
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import (
    add_transaction,
    delete_transaction,
    list_transactions,
    update_transaction,
)
from financial_app.sources.nbp import NbpRates

PLN = "PLN"
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
                    if transaction.instrument_id is not None:
                        assert transaction.quantity is not None and transaction.price is not None
                        instrument = instruments[transaction.instrument_id]
                        ui.label(instrument.name)
                        price = format_unit_price(transaction.price, instrument.quote_currency)
                        ui.label(f"{format_quantity(transaction.quantity)} × {price}").classes("text-xs text-gray-500")
                        if transaction.nbp_rate is not None:
                            rates_text = _rates_text(transaction.fx_rate, transaction.nbp_rate)
                            ui.label(rates_text).classes("text-xs text-gray-500")
                with ui.column().classes("gap-0 items-end"):
                    ui.label(format_pln(transaction.cash_change, signed=True))
                    if transaction.tax_amount != transaction.actual_amount:
                        tax = format_pln(transaction.tax_cash_change, signed=True)
                        ui.label(f"podatkowa {tax}").classes("text-xs text-gray-500")
                ui.label(transaction.comment).classes("text-gray-600")


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
    # Only PLN cash exists so far (foreign cash: issue #16), so only Accounts holding PLN can take part;
    # an edited Transaction keeps offering its own Account even if that has been deactivated since
    accounts = {
        a.id: a.name
        for a in all_accounts
        if (a.active and PLN in a.cash_currencies) or (transaction is not None and a.id == transaction.account_id)
    }
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

        def is_buy_or_sell(value: str) -> bool:
            return TransactionType(value).is_buy_or_sell

        texts = _field_texts(transaction)
        amount = ui.input("Kwota (zł)", value=texts.amount).classes("w-full").mark("transaction-amount")
        amount.bind_visibility_from(transaction_type, "value", backward=lambda value: not is_buy_or_sell(value))
        with ui.column().classes("w-full gap-0") as trade_fields:
            instrument_id = transaction.instrument_id if transaction else None
            instrument = ui.select(instruments, label="Instrument", value=instrument_id).classes("w-full")
            instrument.mark("transaction-instrument")
            if not instruments:
                ui.label("Najpierw dodaj instrument w zakładce Ustawienia.").classes("text-gray-500")
            quantity = ui.input("Liczba", value=texts.quantity).classes("w-full").mark("transaction-quantity")
            price = ui.input("Cena (zł)", value=texts.price).classes("w-full").mark("transaction-price")
            fx_rate = ui.input(value=texts.fx_rate).props('hint="Puste = kurs NBP z dnia roboczego przed datą"')
            fx_rate.classes("w-full").mark("transaction-fx-rate")
            commission = ui.input("Prowizja (zł)", value=texts.commission).classes("w-full")
            commission.mark("transaction-commission")

        def show_currency() -> None:
            """The price is in the Instrument's currency; a foreign one also takes a rate (spec 3.3)."""
            currency = currencies.get(instrument.value, PLN)
            price.props(f'label="Cena ({currency_unit(currency)})"')
            fx_rate.props(f'label="Kurs {currency}/PLN"')
            fx_rate.visible = currency != PLN

        show_currency()
        instrument.on_value_change(show_currency)
        trade_fields.bind_visibility_from(transaction_type, "value", backward=is_buy_or_sell)
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
            if not kind.is_buy_or_sell:
                value = _read(parse_number, amount.value, "Kwota musi być liczbą, np. 1 000,50.")
                return TransactionDraft(account.value, day_value, kind, value, comment.value)
            if instrument.value is None:
                raise TransactionError("Wybierz instrument.")
            currency = currencies[instrument.value]
            nbp_rate = None if currency == PLN else stored_nbp_rate(currency, day_value)
            own_rate = fx_rate.value.strip() if nbp_rate else ""
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
            )

        def save() -> None:
            try:
                draft = read_draft()
                if transaction is None:
                    add_transaction(engine, draft)
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
    quantity: str = ""
    price: str = ""
    fx_rate: str = ""
    commission: str = ""


def _field_texts(transaction: Transaction | None) -> _FieldTexts:
    """The edit-field texts for ``transaction``, exact so that re-saving never rounds a value."""
    if transaction is None:
        return _FieldTexts()
    if not transaction.transaction_type.is_buy_or_sell:
        return _FieldTexts(amount=format_exact(transaction.actual_amount))
    assert transaction.quantity is not None and transaction.price is not None
    return _FieldTexts(
        quantity=format_quantity(transaction.quantity),
        price=format_exact(transaction.price),
        fx_rate="" if transaction.fx_rate is None else format_exact(transaction.fx_rate),
        commission=format_exact(transaction.commission),
    )


def _rates_text(fx_rate: Decimal | None, nbp_rate: NbpRate) -> str:
    """The user's own rate, if any, then the NBP Rate with its table and publication day."""
    nbp = f"NBP {format_exact(nbp_rate.rate)} ({nbp_rate.table} z {format_date(nbp_rate.published_on)})"
    return nbp if fx_rate is None else f"kurs {format_exact(fx_rate)} · {nbp}"


def _warn_if_cash_runs_out(
    engine: Engine, done: str, account_names: dict[int, str], *touched: TransactionDraft | None
) -> None:
    """Warn per Account whose Cash Balance goes negative from the earliest ``touched`` date on.

    Insufficient cash only warns (spec 3.3), so history can be entered in any order. ``done`` opens the
    message ("Zapisano", "Usunięto").
    """
    starts: dict[int, date] = {}
    for t in touched:
        if t is not None:
            starts[t.account_id] = min(t.date, starts.get(t.account_id, t.date))
    transactions = list_transactions(engine)
    for account_id, start in starts.items():
        lowest = lowest_cash_balance(transactions, account_id, start=start)
        if lowest < 0:
            ui.notify(
                f"{done}, ale Saldo gotówki konta {account_names[account_id]} jest ujemne: {format_pln(lowest)}.",
                type="warning",
            )


def _read[T](parse: Callable[[str], T], text: str, message: str) -> T:
    """Parse a form field, turning a parse failure into a TransactionError with ``message``."""
    try:
        return parse(text)
    except ValueError:
        raise TransactionError(message) from None
