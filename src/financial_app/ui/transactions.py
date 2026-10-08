"""The Transakcje tab and the "+" transaction dialog (spec 3.3). For now: PLN Deposits and Withdrawals."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_date, format_pln, parse_date, parse_number
from financial_app.domain.transactions import (
    TransactionDraft,
    TransactionError,
    TransactionType,
    lowest_cash_balance,
)
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.transactions import add_transaction, list_transactions

PLN = "PLN"
TRANSACTION_TYPE_OPTIONS = {transaction_type.value: transaction_type.label for transaction_type in TransactionType}
COLUMNS = "grid-template-columns: 7rem minmax(8rem, 1fr) 6rem 9rem minmax(8rem, 2fr)"


@dataclass
class TransactionsPage:
    """The Transakcje tab."""

    engine: Engine

    def refresh(self) -> None:
        """Redraw the list if it is on screen (e.g. after a save)."""
        self.rows.refresh()

    def build(self) -> None:
        ui.label("Transakcje").classes("text-2xl font-bold")
        # The marker sits outside the refreshable list so it survives a refresh
        with ui.column().classes("w-full max-w-5xl gap-0").mark("transactions"):
            self.rows()

    @ui.refreshable_method
    def rows(self) -> None:
        transactions = list_transactions(self.engine)
        if not transactions:
            ui.label("Brak transakcji. Dodaj pierwszą przyciskiem „+”.").classes("text-gray-500")
            return
        account_names = {account.id: account.name for account in list_accounts(self.engine)}
        with ui.element("div").classes("grid w-full gap-x-4 border-b py-1 font-medium").style(COLUMNS):
            for header in ("Data", "Konto", "Typ", "Kwota", "Komentarz"):
                ui.label(header)
        for transaction in transactions:
            with ui.element("div").classes("grid w-full gap-x-4 border-b py-1").style(COLUMNS):
                ui.label(format_date(transaction.date))
                ui.label(account_names[transaction.account_id])
                ui.label(transaction.transaction_type.label)
                ui.label(format_pln(transaction.cash_change, signed=True)).classes("text-right")
                ui.label(transaction.comment).classes("text-gray-600")


def open_transaction_dialog(engine: Engine, on_saved: Callable[[], None]) -> None:
    """Open a fresh "Nowa transakcja" dialog; it is built on demand and removed when closed."""
    dialog = ui.dialog()
    dialog.on("hide", dialog.delete)
    # Only PLN Deposits and Withdrawals exist so far, so only Accounts holding PLN can take them
    accounts = {a.id: a.name for a in list_accounts(engine) if a.active and PLN in a.cash_currencies}
    with dialog, ui.card().classes("w-[460px]"):
        ui.label("Nowa transakcja").classes("text-lg font-bold")
        if not accounts:
            ui.label("Najpierw dodaj konto z walutą PLN w zakładce Ustawienia.").classes("text-gray-500")
            with ui.row().classes("w-full justify-end"):
                ui.button("Zamknij", on_click=dialog.close).props("flat")
            dialog.open()
            return

        transaction_type = ui.select(TRANSACTION_TYPE_OPTIONS, label="Typ", value=TransactionType.DEPOSIT.value)
        transaction_type.classes("w-full").mark("transaction-type")
        account = ui.select(accounts, label="Konto", value=next(iter(accounts))).classes("w-full")
        account.mark("transaction-account")
        day = ui.input("Data", value=format_date(date.today())).classes("w-full").mark("transaction-date")
        with day.add_slot("append"):
            icon = ui.icon("event").classes("cursor-pointer")
            with ui.menu() as menu:
                ui.date(mask="DD.MM.YYYY").bind_value(day).on_value_change(menu.close)
            icon.on("click", menu.open)
        amount = ui.input("Kwota (zł)").classes("w-full").mark("transaction-amount")
        comment = ui.input("Komentarz").classes("w-full").mark("transaction-comment")
        error = ui.label().classes("text-negative").mark("transaction-error")

        def save() -> None:
            try:
                draft = TransactionDraft(
                    account_id=account.value,
                    date=_read(parse_date, day.value, "Data musi mieć postać DD.MM.RRRR."),
                    transaction_type=TransactionType(transaction_type.value),
                    actual_amount=_read(parse_number, amount.value, "Kwota musi być liczbą, np. 1 000,50."),
                    comment=comment.value,
                )
                add_transaction(engine, draft)
            except TransactionError as exc:
                error.text = str(exc)
                return
            dialog.close()
            _warn_if_cash_runs_out(engine, draft, accounts[draft.account_id])
            on_saved()

        with ui.row().classes("w-full justify-end"):
            ui.button("Anuluj", on_click=dialog.close).props("flat")
            ui.button("Zapisz", on_click=save)
    dialog.open()


def _warn_if_cash_runs_out(engine: Engine, draft: TransactionDraft, account_name: str) -> None:
    """Insufficient cash only warns (spec 3.3), so history can be entered in any order."""
    lowest = lowest_cash_balance(list_transactions(engine), draft.account_id, start=draft.date)
    if lowest < 0:
        ui.notify(
            f"Zapisano, ale Saldo gotówki konta {account_name} jest ujemne: {format_pln(lowest)}.",
            type="warning",
        )


def _read[T](parse: Callable[[str], T], text: str, message: str) -> T:
    """Parse a form field, turning a parse failure into a TransactionError with ``message``."""
    try:
        return parse(text)
    except ValueError:
        raise TransactionError(message) from None
