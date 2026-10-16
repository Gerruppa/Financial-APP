"""The bond data sources in the header (spec 3.4.1): red "Dane obligacji: n błędów" while a source keeps failing,
listing each with its reason and the day of the copy still in use; nothing while all of them work."""

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_count, format_datetime
from financial_app.persistence.bond_data import BondDataStatus, bond_data_statuses
from financial_app.sources.bond_data import BOND_DATA_NAMES


def bond_data_status(engine: Engine) -> None:
    failing = _failing(bond_data_statuses(engine))
    if not failing:
        return
    text = f"Dane obligacji: {format_count(len(failing), 'błąd', 'błędy', 'błędów')}"
    ui.button(text, on_click=lambda: _bond_data_errors_dialog(engine)).props("flat no-caps color=red-4").mark(
        "bond-data-status"
    )


def _failing(statuses: dict[str, BondDataStatus]) -> dict[str, BondDataStatus]:
    return {key: statuses[key] for key in BOND_DATA_NAMES if key in statuses and statuses[key].error is not None}


def _bond_data_errors_dialog(engine: Engine) -> None:
    with ui.dialog() as dialog, ui.card().classes("min-w-96").mark("bond-data-errors"):
        ui.label("Dane obligacji").classes("text-lg font-bold")
        for key, status in _failing(bond_data_statuses(engine)).items():
            ui.label(BOND_DATA_NAMES[key]).classes("font-medium")
            ui.label(status.error or "").classes("text-sm pl-4")
            copy = (
                f"Używane są dane pobrane {format_datetime(status.succeeded_at)}."
                if status.succeeded_at
                else "Brak pobranych danych."
            )
            ui.label(copy).classes("text-sm pl-4 text-gray-500")
        with ui.row().classes("w-full justify-end"):
            ui.button("Zamknij", on_click=dialog.close).props("flat")
    dialog.on("hide", dialog.delete)
    dialog.open()
