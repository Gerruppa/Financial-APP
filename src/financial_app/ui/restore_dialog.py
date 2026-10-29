"""Undoing a delete (``ui/undo.py``) after something changed on its Accounts (#267): before restoring, a window says
what comes back and explains each difference, e.g. the covering Deposits saved since, which would count its cash
twice."""

from collections.abc import Callable, Sequence
from decimal import Decimal

from nicegui import context, ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_date, format_pln
from financial_app.domain.save_warnings import SinceDelete
from financial_app.domain.transactions import Transaction
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.sources.transaction_saving import since_deleted
from financial_app.ui.dialogs import movable_dialog
from financial_app.ui.save_warnings import deposits_total
from financial_app.ui.xtb_import import Describer

# Restores the deleted Transaction, first deleting the Transactions with these ids (covering Deposits)
Restore = Callable[[Sequence[int]], None]


def undo_delete(engine: Engine, deleted: Transaction, left: Sequence[Transaction], restore: Restore) -> None:
    """Restore ``deleted`` at once when nothing changed on its Accounts since the delete left ``left``; otherwise
    open ``restore_dialog`` first."""
    since = since_deleted(engine, deleted, left)
    if since.any:
        restore_dialog(engine, deleted, since, restore)
    else:
        restore(())


def restore_dialog(engine: Engine, deleted: Transaction, since: SinceDelete, restore: Restore) -> None:
    """The window ``undo-window``: what is restored, then each difference ``since`` the delete, with "Przywróć i usuń
    wpłaty uzupełniające" (``undo-drop-covering``) when covering Deposits were saved, "Przywróć bez zmian"
    (``undo-restore``, off while another Transaction holds the id) and "Anuluj" (``undo-cancel``)."""
    describe = Describer(
        {account.id: account.name for account in list_accounts(engine)},
        {instrument.id: instrument.name for instrument in list_instruments(engine)},
    )
    covering_ids = [t.id for t in since.covering]
    # The id is free once the undo drops what holds it, or was never taken
    droppable = bool(covering_ids) and (since.taken_by is None or since.taken_by.id in covering_ids)
    # In the page's layout: the undo bar it was opened from is gone
    with context.client.layout:
        dialog = movable_dialog()
    dialog.on("hide", dialog.delete)
    with dialog, ui.card().classes("w-[36rem] max-w-full").mark("undo-window"):
        ui.label("Cofnąć usunięcie?").classes("text-lg font-bold")
        ui.label(f"Przywrócę: {describe(deleted)}.")
        ui.label("Od usunięcia zmieniło się to, co poniżej; sprawdź, czy przywrócenie wciąż się zgadza.").classes(
            "text-sm k-muted"
        )
        _explain(since, describe)

        def run(dropping: Sequence[int]) -> None:
            dialog.close()
            restore(dropping)

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Anuluj", on_click=dialog.close).props("flat no-caps").mark("undo-cancel")
            keep = ui.button("Przywróć bez zmian", on_click=lambda: run(())).props("flat no-caps")
            keep.mark("undo-restore")
            if since.taken_by is not None:
                keep.disable()
            if droppable:
                ui.button(
                    "Przywróć i usuń wpłaty uzupełniające", icon="undo", on_click=lambda: run(covering_ids)
                ).props("no-caps").mark("undo-drop-covering")
    dialog.open()


def _explain(since: SinceDelete, describe: Describer) -> None:
    """One paragraph per kind of difference, each naming its Transactions."""
    if since.covering:
        total = sum((t.actual_amount for t in since.covering), Decimal(0))
        ui.label(f"Dodano wpłaty uzupełniające: {deposits_total(since.covering)}.").classes("font-medium")
        with ui.column().classes("gap-0 pl-4"):
            for t in since.covering:
                ui.label(f"{format_date(t.date)}: {format_pln(t.actual_amount)}").classes("text-sm")
        ui.label(
            "Pokryły gotówkę, której zabrakło bez usuniętej transakcji. Jeśli je zostawisz, gotówka po przywróceniu "
            f"będzie o {format_pln(total)} wyższa niż przed usunięciem."
        ).classes("text-sm")
    taken = since.taken_by
    if taken is not None and taken in since.covering:
        ui.label(
            f"Wpłata uzupełniająca z {format_date(taken.date)} zajęła jej numer, więc przywrócić ją można tylko razem "
            "z usunięciem wpłat uzupełniających."
        ).classes("text-sm text-negative")
    elif taken is not None:
        ui.label(
            f"Transakcja {describe(taken)} zajęła jej numer, więc nie można jej przywrócić; wpisz ją ponownie "
            "przyciskiem +."
        ).classes("text-sm text-negative")
    others = [
        *(f"Dodano: {describe(t)}" for t in since.added),
        *(f"Zmieniono: {describe(then)} → {describe(now)}" for then, now in since.changed),
        *(f"Usunięto: {describe(t)}" for t in since.removed),
    ]
    for line in others:
        ui.label(line).classes("text-sm")
    if others:
        ui.label(
            "Te zmiany zostaną bez względu na przywrócenie; ostrzeżenia po nim pokażą, jeśli gotówka albo limit wpłat "
            "przestaną się zgadzać."
        ).classes("text-sm k-muted")
