"""Term Deposit rows of the Dochód stały tab's "Do zatwierdzenia" list (issue #160): a period's interest, confirmed at
once or after editing its amounts, and a matured deposit, ended or renewed ("Odnów…") at a new rate."""

from collections.abc import Callable
from dataclasses import replace

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_date, format_exact, format_pln, parse_date, parse_number
from financial_app.domain.term_deposits import DepositMaturityDraft, InterestDraft, TermDepositError
from financial_app.domain.transactions import TransactionError, dividend
from financial_app.persistence.deposit_drafts import confirm_interest
from financial_app.persistence.term_deposits import close_deposit, renew_deposit
from financial_app.persistence.transactions import add_transaction
from financial_app.sources.transaction_saving import checked_save
from financial_app.ui.dialogs import movable_dialog
from financial_app.ui.save_warnings import show_warnings


def interest_row(engine: Engine, draft: InterestDraft, name_account: bool, on_saved: Callable[[], None]) -> None:
    period = draft.period
    with ui.row().classes("w-full items-center border-b py-1 gap-4").mark("deposit-draft"):
        with ui.column().classes("gap-0 grow"):
            title = f"Odsetki {draft.deposit.name}"
            ui.label(f"{title} · {draft.account.name}" if name_account else title).classes("font-medium")
            ui.label(
                f"okres {period.number} · {format_date(period.start)}–{format_date(period.end)} · "
                f"kapitał {format_pln(period.capital)}"
            ).classes("text-sm k-muted")
        with ui.column().classes("gap-0 items-end"):
            ui.label(f"Wypłata netto {format_pln(period.net)}").classes("font-medium")
            ui.label(f"podatek {format_pln(period.tax)}").classes("text-xs k-muted")

        def confirm() -> None:
            try:
                saved = checked_save(engine, lambda: confirm_interest(engine, draft))
            except TransactionError as exc:
                ui.notify(str(exc), type="negative")
                return
            ui.notify(f"Zapisano odsetki {draft.deposit.name}.", type="positive")
            show_warnings(saved.warnings)
            on_saved()

        ui.button("Zatwierdź odsetki", on_click=confirm).props("flat").mark("confirm-deposit-interest")
        ui.button("Edytuj…", on_click=lambda: _interest_dialog(engine, draft, on_saved)).props("flat").mark(
            "edit-deposit-interest"
        )


def _interest_dialog(engine: Engine, draft: InterestDraft, on_saved: Callable[[], None]) -> None:
    """The period's interest as the bank paid it: its day, gross amount and tax, still linked to the period."""
    period = draft.period
    dialog = movable_dialog()
    dialog.on("hide", dialog.delete)
    with dialog, ui.card().classes("min-w-96").mark("interest-dialog"):
        ui.label(f"Odsetki {draft.deposit.name} · okres {period.number}").classes("text-lg font-bold")
        day = ui.input("Data", value=format_date(period.end)).classes("w-full").mark("interest-date")
        gross = ui.input("Odsetki brutto (zł)", value=format_exact(period.gross)).classes("w-full")
        gross.mark("interest-gross")
        tax = ui.input("Podatek pobrany (zł)", value=format_exact(period.tax)).classes("w-full").mark("interest-tax")
        error = ui.label().classes("text-negative").mark("interest-error")

        def save() -> None:
            try:
                paid = dividend(
                    draft.account.id,
                    parse_date(day.value or ""),
                    parse_number(gross.value or ""),
                    parse_number(tax.value or ""),
                    draft.transaction().comment,
                )
            except TransactionError as exc:
                error.text = str(exc)
                return
            except ValueError:
                error.text = "Podaj datę DD.MM.RRRR i kwoty jako liczby, np. 50,96."
                return
            linked = replace(paid, term_deposit_id=draft.deposit.id, term_deposit_period=period.end)
            try:
                saved = checked_save(engine, lambda: add_transaction(engine, linked))
            except TransactionError as exc:
                error.text = str(exc)
                return
            dialog.close()
            ui.notify(f"Zapisano odsetki {draft.deposit.name}.", type="positive")
            show_warnings(saved.warnings)
            on_saved()

        with ui.row().classes("w-full justify-end"):
            ui.button("Anuluj", on_click=dialog.close).props("flat")
            ui.button("Zapisz", on_click=save).mark("save-interest")
    dialog.open()


def maturity_row(
    engine: Engine, draft: DepositMaturityDraft, name_account: bool, on_changed: Callable[[], None]
) -> None:
    deposit = draft.deposit
    with ui.row().classes("w-full items-center border-b py-1 gap-4").mark("deposit-draft"):
        with ui.column().classes("gap-0 grow"):
            title = f"Zapadalność {deposit.name}"
            ui.label(f"{title} · {draft.account.name}" if name_account else title).classes("font-medium")
            ui.label(f"od {format_date(deposit.start_date)} · koniec {format_date(draft.due)}").classes(
                "text-sm k-muted"
            )
        ui.label(f"Kapitał z odsetkami {format_pln(draft.final_capital)}").classes("font-medium")

        def end() -> None:
            try:
                close_deposit(engine, deposit.id, draft.due)
            except TermDepositError as exc:
                ui.notify(str(exc), type="negative")
                return
            ui.notify(f"Zakończono lokatę {deposit.name}.", type="positive")
            on_changed()

        renew = ui.button("Odnów…", on_click=lambda: _renew_dialog(engine, draft, on_changed)).mark("renew-deposit")
        end_button = ui.button("Zakończ", on_click=end).mark("end-deposit")
        # A renewable deposit offers "Odnów" first, any other "Zakończ"
        (end_button if deposit.renew else renew).props("flat")


def _renew_dialog(engine: Engine, draft: DepositMaturityDraft, on_changed: Callable[[], None]) -> None:
    """The same deposit again from its maturity, of its whole capital, at the rate the bank offers now."""
    dialog = movable_dialog()
    dialog.on("hide", dialog.delete)
    with dialog, ui.card().classes("min-w-96").mark("renew-dialog"):
        ui.label(f"Odnów {draft.deposit.name}").classes("text-lg font-bold")
        ui.label(f"Od {format_date(draft.due)} · kapitał {format_pln(draft.final_capital)}").classes("text-sm k-muted")
        rate = ui.input("Oprocentowanie (% w skali roku)", value=format_exact(draft.deposit.annual_rate))
        rate.classes("w-full").mark("renew-rate")
        error = ui.label().classes("text-negative").mark("renew-error")

        def save() -> None:
            try:
                renewed = renew_deposit(engine, draft, parse_number(rate.value or ""))
            except TermDepositError as exc:
                error.text = str(exc)
                return
            except ValueError:
                error.text = "Oprocentowanie musi być liczbą, np. 5,5."
                return
            dialog.close()
            ui.notify(f"Odnowiono lokatę {renewed.name} do {format_date(renewed.maturity)}.", type="positive")
            on_changed()

        with ui.row().classes("w-full justify-end"):
            ui.button("Anuluj", on_click=dialog.close).props("flat")
            ui.button("Zapisz", on_click=save).mark("save-renew")
    dialog.open()
