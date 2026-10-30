"""The Contribution Limits help window (issue #273), opened from a Deposit into an IKE, IKZE or OIPE in the "+" dialog:
the year's limits, what counts towards them and what to do with a Deposit over one."""

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.contribution_limits import IKZE_SELF_EMPLOYED, LIMITED_TYPES
from financial_app.domain.formatting import format_pln
from financial_app.persistence.contribution_limits import load_limits
from financial_app.ui.dialogs import movable_dialog

COUNTS = (
    "Limit to suma wpłat w roku kalendarzowym na wszystkie konta jednego typu razem, np. na dwa IKE.",
    "Liczą się wpłaty i przelewy gotówki na takie konto z konta innego typu, np. ze zwykłego na IKE.",
    "Przeniesienie IKE do innej instytucji (przelew z IKE na IKE) nie jest wpłatą i się nie liczy.",
    "Wypłaty nie zwalniają limitu: liczy się, ile wpłacono, nie ile zostało na koncie.",
)

OVER = (
    "Wpłata ponad limit nie korzysta z ulgi; instytucja zwykle zwraca nadwyżkę na Twoje konto.",
    "W oknie wpłaty przycisk „Podziel wpłatę” zapisze wpłatę do limitu i resztę na wybrane zwykłe konto.",
    "Jeśli nadwyżka naprawdę została na koncie, zapisz wpłatę tak, jak ją wpisałeś: aplikacja tylko ostrzeże.",
)


def open_limits_guide(engine: Engine, year: int) -> None:
    """Open the help window on ``year``'s limits, as set in Ustawienia > Limity i reguły."""
    dialog = movable_dialog()
    dialog.on("hide", dialog.delete)
    with dialog, ui.card().classes("w-[560px] max-w-[95vw] max-h-[85vh] overflow-auto gap-2").mark("limits-guide"):
        with ui.row().classes("w-full items-start no-wrap"):
            ui.label("Limity wpłat IKE, IKZE i OIPE").classes("text-lg font-bold grow")
            ui.button(icon="close", on_click=dialog.close).props('flat round dense aria-label="Zamknij pomoc"')
        ui.label(f"Limity na {year}").classes("font-bold")
        limits = load_limits(engine).get(year, {})
        for account_type in LIMITED_TYPES:
            limit = limits.get(account_type)
            amount = "nie ustawiono" if limit is None else format_pln(limit)
            ui.label(f"{account_type.label}: {amount}").classes("text-sm")
        if year in IKZE_SELF_EMPLOYED:
            ui.label(f"IKZE prowadzących działalność gospodarczą: {format_pln(IKZE_SELF_EMPLOYED[year])}.").classes(
                "text-sm k-muted"
            )
        ui.label("Limity zmienisz w Ustawieniach > Limity i reguły.").classes("text-xs k-muted")
        ui.label("Co liczy się do limitu").classes("font-bold mt-2")
        for text in COUNTS:
            ui.label(f"• {text}").classes("text-sm")
        ui.label("Wpłata ponad limit").classes("font-bold mt-2")
        for text in OVER:
            ui.label(f"• {text}").classes("text-sm")
    dialog.open()
