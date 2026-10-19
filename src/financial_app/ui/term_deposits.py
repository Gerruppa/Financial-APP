"""The Lokaty section of the Dochód stały tab (issue #160): the running Term Deposits of the View Scope with their
accrued interest and what breaking them today pays, and the dialog adding, editing, breaking or deleting one."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.formatting import (
    format_date,
    format_exact,
    format_exact_percent,
    format_pln,
    parse_date,
    parse_number,
)
from financial_app.domain.term_deposits import (
    Capitalization,
    DepositRow,
    TermDeposit,
    TermDepositDraft,
    TermDepositError,
    TermUnit,
    deposit_rows,
    interest_periods,
    needs_capital,
    tax_rate_of,
)
from financial_app.domain.transactions import (
    PLN,
    TransactionError,
    TransactionType,
    cash_transfer,
    deposit_or_withdrawal,
)
from financial_app.persistence.term_deposits import add_deposit, close_deposit, delete_deposit, update_deposit
from financial_app.persistence.transactions import add_transaction
from financial_app.sources.todays_view import TodaysView
from financial_app.sources.transaction_saving import checked_save
from financial_app.ui.dialogs import movable_dialog
from financial_app.ui.save_warnings import show_warnings

CAPITALIZATION_LABELS = {
    Capitalization.AT_MATURITY: "na koniec",
    Capitalization.MONTHLY: "co miesiąc",
    Capitalization.QUARTERLY: "co kwartał",
    Capitalization.SEMIANNUAL: "co pół roku",
    Capitalization.YEARLY: "co rok",
}
UNIT_LABELS = {TermUnit.MONTHS: "miesięcy", TermUnit.DAYS: "dni"}
# Where a new deposit's capital comes from: not recorded, a Deposit into its Account, or a Cash Transfer from another
NO_CAPITAL = "none"
CAPITAL_DEPOSIT = "deposit"
TRANSFER_FROM = "transfer-"

COLUMNS = "grid-template-columns: minmax(10rem, 2fr) repeat(6, minmax(6rem, 1fr))"
HEADERS = ("Lokata", "Kapitał", "Oprocentowanie", "Zapadalność", "Dni do końca", "Narosłe odsetki", "Przy zerwaniu")


@dataclass(frozen=True)
class DepositsSection:
    """The section: ``on_changed`` runs after a deposit is added, edited, broken or deleted, ``on_saved`` after the
    capital's Transaction is saved."""

    engine: Engine
    view: TodaysView
    account_id: int | None
    on_changed: Callable[[], None]
    on_saved: Callable[[], None]

    def build(self) -> None:
        with ui.row().classes("w-full items-center mt-2"):
            ui.label("Lokaty").classes("text-lg font-bold")
            ui.space()
            if _holding_accounts(self.view.accounts):
                ui.button("Dodaj lokatę", icon="add", on_click=lambda: self.open_dialog(None)).props("flat").mark(
                    "add-deposit"
                )
        rows = deposit_rows(
            self.view.deposits, self.view.accounts, self.view.transactions, self.view.today, self.account_id
        )
        with ui.column().classes("w-full gap-0").mark("term-deposits"):
            if not rows:
                text = "Brak trwających lokat."
                if not _holding_accounts(self.view.accounts):
                    text += " Lokatę założysz na koncie typu „Lokata / oszczędności” (Ustawienia → Konta)."
                ui.label(text).classes("text-gray-500").mark("deposits-empty")
                return
            with ui.element("div").classes("grid w-full gap-x-4 border-b py-1 font-medium").style(COLUMNS):
                for header in HEADERS:
                    ui.label(header).classes("" if header == "Lokata" else "text-right")
            for row in rows:
                self._row(row)

    def _row(self, row: DepositRow) -> None:
        deposit = row.deposit
        line = ui.element("div").classes("grid w-full gap-x-4 border-b py-1 cursor-pointer hover:bg-gray-100")
        with line.style(COLUMNS).mark("deposit-row"):
            with ui.column().classes("gap-0"):
                ui.label(deposit.name).classes("font-medium")
                details = f"od {format_date(deposit.start_date)} · {CAPITALIZATION_LABELS[deposit.capitalization]}"
                if self.account_id is None:
                    details = f"{row.account.name} · {details}"
                ui.label(details).classes("text-xs text-gray-500")
            ui.label(format_pln(deposit.principal)).classes("text-right")
            ui.label(format_exact_percent(deposit.annual_rate)).classes("text-right")
            ui.label(format_date(deposit.maturity)).classes("text-right")
            ui.label(str(row.days_left)).classes("text-right")
            with ui.column().classes("gap-0 items-end"):
                ui.label(format_pln(row.accrued.net))
                ui.label(f"podatek {format_pln(row.accrued.tax)}").classes("text-xs text-gray-500")
            ui.label(format_pln(row.break_value)).classes("text-right font-medium")
        line.on("click", lambda: self.open_dialog(deposit))

    def open_dialog(self, deposit: TermDeposit | None) -> None:
        open_deposit_dialog(self.engine, self.view, self.account_id, deposit, self.on_changed, self.on_saved)


def _holding_accounts(accounts: list[Account]) -> list[Account]:
    """The Accounts a Term Deposit may be added on: active Deposit Accounts holding PLN."""
    return [a for a in accounts if a.account_type is AccountType.DEPOSIT and a.active and PLN in a.cash_currencies]


def open_deposit_dialog(
    engine: Engine,
    view: TodaysView,
    scope_account_id: int | None,
    deposit: TermDeposit | None,
    on_changed: Callable[[], None],
    on_saved: Callable[[], None],
) -> None:
    """A new deposit (``None``) on an Account of the View Scope by default, its capital optionally recorded too, or
    ``deposit`` to edit, break or delete."""
    accounts = _holding_accounts(view.accounts)
    if deposit is not None and all(a.id != deposit.account_id for a in accounts):
        accounts += [a for a in view.accounts if a.id == deposit.account_id]
    by_id = {a.id: a for a in view.accounts}
    dialog = movable_dialog()
    dialog.on("hide", dialog.delete)
    with dialog, ui.card().classes("min-w-[28rem]").mark("deposit-dialog"):
        ui.label("Nowa lokata" if deposit is None else "Edytuj lokatę").classes("text-lg font-bold")
        default = deposit.account_id if deposit else scope_account_id
        if default not in {a.id for a in accounts}:
            default = accounts[0].id if accounts else None
        account = ui.select({a.id: a.name for a in accounts}, value=default, label="Konto").classes("w-full")
        account.props("filled bg-color=blue-1")
        account.mark("deposit-account")
        name = ui.input("Nazwa", value=deposit.name if deposit else "").classes("w-full").mark("deposit-name")
        principal = ui.input("Kwota (zł)", value=format_exact(deposit.principal) if deposit else "")
        principal.classes("w-full").mark("deposit-principal")
        start = ui.input("Data założenia", value=format_date(deposit.start_date if deposit else view.today))
        start.classes("w-full").mark("deposit-start")
        with ui.row().classes("w-full no-wrap"):
            term = ui.input("Okres", value=str(deposit.term_count) if deposit else "").classes("grow")
            term.mark("deposit-term")
            unit = ui.select(
                {u.value: label for u, label in UNIT_LABELS.items()},
                value=(deposit.term_unit if deposit else TermUnit.MONTHS).value,
                label="Jednostka",
            ).mark("deposit-term-unit")
        rate = ui.input("Oprocentowanie (% w skali roku)", value=format_exact(deposit.annual_rate) if deposit else "")
        rate.classes("w-full").mark("deposit-rate")
        capitalization = ui.select(
            {c.value: label for c, label in CAPITALIZATION_LABELS.items()},
            value=(deposit.capitalization if deposit else Capitalization.AT_MATURITY).value,
            label="Kapitalizacja odsetek",
        ).classes("w-full")
        capitalization.mark("deposit-capitalization")
        renew = ui.checkbox("Odnawialna (w terminie proponuj „Odnów”)", value=deposit.renew if deposit else False)
        renew.mark("deposit-renew")
        capital = None
        if deposit is None:
            sources = {NO_CAPITAL: "Nie zapisuj", CAPITAL_DEPOSIT: "Wpłata na konto lokaty"}
            sources |= {
                f"{TRANSFER_FROM}{a.id}": f"Transfer z konta {a.name}"
                for a in view.accounts
                if a.active and PLN in a.cash_currencies and a.account_type is not AccountType.DEPOSIT
            }
            capital = ui.select(sources, value=NO_CAPITAL, label="Zapisz też przelanie kapitału").classes("w-full")
            capital.mark("deposit-capital")
            ui.label(
                "Sama lokata nie trafia do Transakcji: zapisują się tam jej kapitał (to pole) i zatwierdzone odsetki."
            ).classes("text-xs text-gray-500").mark("deposit-capital-hint")
        # The capital's source follows whether the Account holds it on the start, until the user picks one
        picked = False
        defaulting = False

        def capital_picked() -> None:
            nonlocal picked
            picked = picked or not defaulting

        if capital is not None:
            capital.on_value_change(capital_picked)
        summary = ui.label().classes("text-sm text-gray-600").mark("deposit-summary")
        error = ui.label().classes("text-negative").mark("deposit-error")

        def draft() -> TermDepositDraft:
            if account.value is None:
                raise TermDepositError("Wybierz konto.")
            try:
                amount = parse_number(principal.value or "")
            except ValueError:
                raise TermDepositError("Kwota musi być liczbą, np. 10 000.") from None
            try:
                started = parse_date(start.value or "")
            except ValueError:
                raise TermDepositError("Data założenia musi mieć postać DD.MM.RRRR.") from None
            try:
                count = int(parse_number(term.value or ""))
            except ValueError:
                raise TermDepositError("Okres musi być liczbą, np. 3.") from None
            try:
                percent = parse_number(rate.value or "")
            except ValueError:
                raise TermDepositError("Oprocentowanie musi być liczbą, np. 5,5.") from None
            return TermDepositDraft(
                account_id=account.value,
                name=name.value or "",
                principal=amount,
                start_date=started,
                term_count=count,
                term_unit=TermUnit(unit.value),
                annual_rate=percent,
                capitalization=Capitalization(capitalization.value),
                renew=renew.value,
                closed_on=deposit.closed_on if deposit else None,
            )

        def show() -> None:
            nonlocal defaulting
            try:
                shown = draft()
            except TermDepositError:
                summary.text = ""
                return
            periods = interest_periods(shown, tax_rate_of(by_id[shown.account_id]))
            net = sum((p.net for p in periods), Decimal(0))
            summary.text = f"Zapadalność {format_date(shown.maturity)} · odsetki netto na koniec {format_pln(net)}"
            if capital is not None and not picked:
                defaulting = True
                needed = needs_capital(view.transactions, shown.account_id, shown.start_date, shown.principal)
                capital.value = CAPITAL_DEPOSIT if needed else NO_CAPITAL
                defaulting = False

        def save() -> None:
            try:
                fields = draft()
                saved = add_deposit(engine, fields) if deposit is None else update_deposit(engine, deposit.id, fields)
            except TermDepositError as exc:
                error.text = str(exc)
                return
            dialog.close()
            ui.notify(f"Zapisano lokatę {saved.name}.", type="positive")
            if capital is not None and capital.value != NO_CAPITAL:
                _save_capital(engine, saved, capital.value, on_saved)
            on_changed()

        for field in (account, principal, start, term, unit, rate, capitalization):
            field.on_value_change(show)
        show()
        if deposit is not None:
            _break_row(engine, deposit, view.today, dialog, error, on_changed)
        with ui.row().classes("w-full justify-end"):
            if deposit is not None:
                ui.button("Usuń", on_click=lambda: _confirm_delete(engine, deposit, dialog, on_changed)).props(
                    "flat color=negative"
                ).mark("delete-deposit")
            ui.space()
            ui.button("Anuluj", on_click=dialog.close).props("flat")
            ui.button("Zapisz", on_click=save).mark("save-deposit")
    dialog.open()


def _save_capital(engine: Engine, deposit: TermDeposit, source: str, on_saved: Callable[[], None]) -> None:
    """Record the deposit's capital reaching its Account on its start: a Deposit, or a Cash Transfer from another."""
    comment = f"Kapitał lokaty {deposit.name}"
    if source == CAPITAL_DEPOSIT:
        paid = deposit_or_withdrawal(
            deposit.account_id, deposit.start_date, TransactionType.DEPOSIT, deposit.principal, comment
        )
    else:
        source_id = int(source.removeprefix(TRANSFER_FROM))
        paid = cash_transfer(source_id, deposit.start_date, deposit.account_id, deposit.principal, comment)
    try:
        saved = checked_save(engine, lambda: add_transaction(engine, paid))
    except TransactionError as exc:
        ui.notify(str(exc), type="negative")
        return
    show_warnings(saved.warnings)
    on_saved()


def _break_row(
    engine: Engine,
    deposit: TermDeposit,
    today: date,
    dialog: ui.dialog,
    error: ui.label,
    on_changed: Callable[[], None],
) -> None:
    """ "Zerwij lokatę": end it before maturity, forfeiting the interest of the period running then."""
    ui.separator()
    with ui.row().classes("w-full items-center no-wrap"):
        day = ui.input("Data zerwania", value=format_date(min(today, deposit.maturity))).classes("grow")
        day.mark("deposit-break-date")

        def broken() -> None:
            try:
                close_deposit(engine, deposit.id, parse_date(day.value or ""))
            except TermDepositError as exc:
                error.text = str(exc)
                return
            except ValueError:
                error.text = "Data zerwania musi mieć postać DD.MM.RRRR."
                return
            dialog.close()
            ui.notify(f"Zerwano lokatę {deposit.name}.", type="positive")
            on_changed()

        ui.button("Zerwij lokatę", on_click=broken).props("flat color=warning").mark("break-deposit")


def _confirm_delete(engine: Engine, deposit: TermDeposit, dialog: ui.dialog, on_changed: Callable[[], None]) -> None:
    with ui.dialog() as confirm, ui.card().mark("confirm-delete-deposit-dialog"):
        ui.label(f"Usunąć lokatę {deposit.name}? Zapisane odsetki zostaną, bez powiązania z lokatą.")

        def deleted() -> None:
            try:
                delete_deposit(engine, deposit.id)
            except TermDepositError as exc:
                ui.notify(str(exc), type="negative")
                return
            confirm.close()
            dialog.close()
            ui.notify(f"Usunięto lokatę {deposit.name}.", type="positive")
            on_changed()

        with ui.row().classes("w-full justify-end"):
            ui.button("Anuluj", on_click=confirm.close).props("flat")
            ui.button("Usuń", on_click=deleted).props("color=negative").mark("confirm-delete-deposit")
    confirm.on("hide", confirm.delete)
    confirm.open()
