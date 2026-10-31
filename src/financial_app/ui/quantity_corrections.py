"""Choosing the quantity correction of each Sell or Security Transfer left uncovered (#278), the same way in the
crypto import, the XTB import and the transaction dialog: what it lacks, about what it is worth, and a fix per row,
each saying what it changes in cost and realised result."""

from collections.abc import Callable, Sequence

from nicegui import ui

from financial_app.domain.formatting import format_count, format_percent, format_pln, format_quantity
from financial_app.domain.quantity_corrections import CORRECTION_COMMENT, LARGE_GAP, Fix, Shortfall
from financial_app.domain.transactions import TransactionDraft

LARGE_WARNING = (
    f"Różnica przekracza {format_percent(LARGE_GAP * 100, 0)} liczby: bardziej prawdopodobne, że brakuje zakupu "
    "albo transferu niż opłaty. Sprawdź "
    "historię, zanim wybierzesz poprawkę."
)
HINT = (
    "Sprzedaż albo transfer wymaga trochę więcej jednostek, niż było na koncie: zwykle to opłata pobrana w monecie "
    f"albo zaokrąglenie w eksporcie. Dodany zakup ma komentarz „{CORRECTION_COMMENT}”."
)


def shortfall_text(shortfall: Shortfall) -> str:
    """E.g. "Brakuje 0,001 szt. (ok. 0,11 zł): na koncie było 2 szt., a sprzedaż wymaga 2,001 szt."."""
    value = "" if shortfall.value is None else f" (ok. {format_pln(shortfall.value)})"
    what = "sprzedaż" if shortfall.is_sell else "transfer"
    return (
        f"Brakuje {format_quantity(shortfall.gap)} szt.{value}: na koncie było {format_quantity(shortfall.held)} "
        f"szt., a {what} wymaga {format_quantity(shortfall.quantity)} szt."
    )


def corrections_total(shortfalls: Sequence[Shortfall]) -> str:
    """E.g. "2 poprawki ilości"."""
    return format_count(len(shortfalls), "poprawka ilości", "poprawki ilości", "poprawek ilości")


def correction_choices(
    shortfalls: Sequence[Shortfall],
    describe: Callable[[TransactionDraft], str],
    choose: Callable[[str, Fix], None],
    marker: str,
) -> None:
    """One block per shortfall (``<marker>-<n>``, from 1): the uncovered Transaction, what it lacks, the warning above
    1% and a radio of its fixes (``<marker>-fix-<n>``), none picked for a large gap; ``choose`` hears a pick."""
    for number, shortfall in enumerate(shortfalls, start=1):
        with ui.column().classes("w-full gap-1 border-b py-1").mark(f"{marker}-{number}"):
            ui.label(describe(shortfall.uncovered)).classes("text-sm font-bold")
            ui.label(shortfall_text(shortfall)).classes("text-sm")
            if shortfall.large:
                ui.label(LARGE_WARNING).classes("text-sm k-warning").mark(f"{marker}-large-{number}")
            options = {fix.value: f"{fix.label}. {shortfall.effect(fix)}" for fix in shortfall.fixes}
            ui.radio(
                options,
                value=None if shortfall.fix is None else shortfall.fix.value,
                on_change=lambda e, key=shortfall.key: _picked(choose, key, e.value),
            ).props("dense").classes("text-sm").mark(f"{marker}-fix-{number}")


def _picked(choose: Callable[[str, Fix], None], key: str, value: str | None) -> None:
    if value:
        choose(key, Fix(value))
