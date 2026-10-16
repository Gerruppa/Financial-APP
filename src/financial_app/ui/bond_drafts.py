"""The "Do zatwierdzenia" list of the Obligacje tab and its count in the header (spec 3.4.1, L-6, L-8): each Lot of a
Bond Series held past its maturity, confirmed as its redemption or as a Rollover ("roluj do…") into a new Series, and
each coupon of a COI, ROR or DOR Lot paid but not entered, confirmed as interest."""

from collections.abc import Callable
from datetime import date

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.bond_drafts import ROLLOVER_TYPES, CouponDraft, MaturityDraft
from financial_app.domain.bonds import BondType
from financial_app.domain.formatting import format_date, format_pln, format_quantity, parse_number
from financial_app.domain.instruments import InstrumentError
from financial_app.domain.transactions import TransactionError
from financial_app.persistence.bond_drafts import confirm_draft, confirm_rollover, pending_drafts, rollover_price
from financial_app.sources.transaction_saving import checked_save
from financial_app.ui.save_warnings import show_warnings


def drafts_list(engine: Engine, today: date, account_id: int | None, on_saved: Callable[[], None]) -> None:
    """The Drafts due in the View Scope (``account_id``), nothing when there are none."""
    drafts = pending_drafts(engine, today, account_id)
    if not drafts:
        return
    with ui.card().classes("w-full mb-4 bg-amber-50").mark("bond-drafts"):
        ui.label("Do zatwierdzenia").classes("text-lg font-bold")
        for draft in drafts:
            if isinstance(draft, CouponDraft):
                _coupon_row(engine, draft, account_id is None, on_saved)
            else:
                _draft_row(engine, draft, account_id is None, on_saved)


def _coupon_row(engine: Engine, draft: CouponDraft, name_account: bool, on_saved: Callable[[], None]) -> None:
    with ui.row().classes("w-full items-center border-b py-1 gap-4").mark("bond-draft"):
        with ui.column().classes("gap-0 grow"):
            title = f"Odsetki {draft.instrument.name}"
            ui.label(f"{title} · {draft.account.name}" if name_account else title).classes("font-medium")
            ui.label(
                f"{format_quantity(draft.lot.quantity)} szt. · zakup {format_date(draft.lot.date)} · "
                f"okres {draft.period} · {format_date(draft.due)}"
            ).classes("text-sm text-gray-600")
        with ui.column().classes("gap-0 items-end"):
            ui.label(f"Wypłata netto {format_pln(draft.net)}").classes("font-medium")
            ui.label(f"podatek {format_pln(draft.tax)}").classes("text-xs text-gray-500")

        def confirm() -> None:
            try:
                saved = checked_save(engine, lambda: confirm_draft(engine, draft))
            except TransactionError as exc:
                ui.notify(str(exc), type="negative")
                return
            ui.notify(f"Zapisano odsetki {draft.instrument.name}.", type="positive")
            show_warnings(saved.warnings)
            on_saved()

        ui.button("Zatwierdź odsetki", on_click=confirm).props("flat").mark("confirm-coupon")


def _draft_row(engine: Engine, draft: MaturityDraft, name_account: bool, on_saved: Callable[[], None]) -> None:
    with ui.row().classes("w-full items-center border-b py-1 gap-4").mark("bond-draft"):
        with ui.column().classes("gap-0 grow"):
            title = f"Wykup {draft.instrument.name}"
            ui.label(f"{title} · {draft.account.name}" if name_account else title).classes("font-medium")
            ui.label(
                f"{format_quantity(draft.lot.quantity)} szt. · zakup {format_date(draft.lot.date)} · "
                f"wykup {format_date(draft.maturity)}"
            ).classes("text-sm text-gray-600")
        redemption = draft.redemption
        if redemption is None:
            ui.label("Seria bez wyceny: wpisz wykup przyciskiem „+”.").classes("text-sm text-gray-500")
            return
        with ui.column().classes("gap-0 items-end"):
            ui.label(f"Wypłata netto {format_pln(redemption.net)}").classes("font-medium")
            ui.label(f"podatek {format_pln(redemption.tax)}").classes("text-xs text-gray-500")

        def redeem() -> None:
            try:
                saved = checked_save(engine, lambda: confirm_draft(engine, draft))
            except TransactionError as exc:
                ui.notify(str(exc), type="negative")
                return
            ui.notify(f"Zapisano wykup {draft.instrument.name}.", type="positive")
            show_warnings(saved.warnings)
            on_saved()

        ui.button("Zatwierdź wykup", on_click=redeem).props("flat").mark("confirm-redemption")
        ui.button("Roluj do…", on_click=lambda: _rollover_dialog(engine, draft, on_saved)).props("flat").mark(
            "rollover"
        )


def _rollover_dialog(engine: Engine, draft: MaturityDraft, on_saved: Callable[[], None]) -> None:
    """Redeem the Lot and buy a new Series that day at its Rollover price; as many bonds as matured by default."""
    with ui.dialog() as dialog, ui.card().classes("min-w-96").mark("rollover-dialog"):
        ui.label(f"Zamiana {draft.instrument.name}").classes("text-lg font-bold")
        # A family bond is never bought in a Rollover, so a matured one rolls into EDO by default
        default = draft.bond_type if draft.bond_type in ROLLOVER_TYPES else BondType.EDO
        bond_type = ui.select([str(t) for t in ROLLOVER_TYPES], value=str(default), label="Typ obligacji")
        bond_type.classes("w-full").mark("rollover-type")
        quantity = ui.input("Liczba obligacji", value=format_quantity(draft.lot.quantity)).classes("w-full")
        quantity.mark("rollover-quantity")
        summary = ui.label().classes("text-sm text-gray-600").mark("rollover-summary")
        error = ui.label().classes("text-negative").mark("rollover-error")

        def show() -> None:
            name = draft.rollover_series(BondType(bond_type.value))
            price = rollover_price(engine, name)
            summary.text = f"Seria {name} · cena zamiany {format_pln(price)} · zakup {format_date(draft.maturity)}"

        def save() -> None:
            try:
                units = parse_number(quantity.value)
            except ValueError:
                error.text = "Liczba musi być liczbą, np. 10."
                return
            try:
                saved = checked_save(engine, lambda: confirm_rollover(engine, draft, BondType(bond_type.value), units))
            except (TransactionError, InstrumentError) as exc:
                error.text = str(exc)
                return
            dialog.close()
            ui.notify(f"Zapisano zamianę {draft.instrument.name}.", type="positive")
            show_warnings(saved.warnings)
            on_saved()

        show()
        bond_type.on_value_change(show)
        with ui.row().classes("w-full justify-end"):
            ui.button("Anuluj", on_click=dialog.close).props("flat")
            ui.button("Zapisz", on_click=save).mark("save-rollover")
    dialog.on("hide", dialog.delete)
    dialog.open()


def drafts_count(engine: Engine, today: date) -> None:
    """ "Do zatwierdzenia: n" in the header while any Draft is due in any Account; clicking opens the Obligacje tab."""
    count = len(pending_drafts(engine, today))
    if not count:
        return
    ui.button(f"Do zatwierdzenia: {count}", on_click=lambda: ui.navigate.to("/obligacje")).props(
        "flat no-caps color=amber-4"
    ).mark("drafts-count")
