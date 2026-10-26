"""The commands of the palette in the header search (``ui/header_search.py``): a command for each tab and the actions
the header and the avatar menu also have. What finds a command is in ``domain/commands.py``."""

from collections.abc import Callable, Iterable
from functools import partial

from financial_app.domain.commands import Command
from financial_app.ui.header_search import PaletteCommand

# Words besides its label that find a tab, by its path
TAB_KEYWORDS = {
    "/": ("start", "pulpit"),
    "/wyniki": ("zysk", "xirr", "stopa"),
    "/portfolio": ("pozycje", "aktywa"),
    "/transakcje": ("historia", "operacje"),
    "/strategie": ("alokacja", "cel"),
    "/obligacje": ("obligacje", "lokaty", "depozyty"),
    "/benchmarki": ("porównanie", "indeksy"),
    "/sprzedaz": ("sprzedaż", "fifo", "podatek"),
    "/dochod-pasywny": ("dywidendy", "odsetki", "kupony"),
    "/ustawienia": ("konta", "instrumenty", "import", "wygląd"),
    "/pomoc": ("faq", "help"),
}


def palette_commands(
    tabs: Iterable[tuple[str, str, str]],
    *,
    go_to: Callable[[str], object],
    add_transaction: Callable[[], object],
    switch_theme: Callable[[], object],
    switch_discreet: Callable[[], object],
    refresh_prices: Callable[[], object],
    switch_user: Callable[[], object] | None = None,
) -> list[PaletteCommand]:
    """A "Przejdź do: <tab>" command for each ``(label, path, icon)`` in ``tabs``, then the actions; "Przełącz
    użytkownika" only with ``switch_user`` (the demo has no login screen to return to)."""
    commands = [
        PaletteCommand(
            Command(f"go:{path}", f"Przejdź do: {label}", TAB_KEYWORDS.get(path, ())),
            icon,
            partial(go_to, path),
        )
        for label, path, icon in tabs
    ]
    commands += [
        PaletteCommand(
            Command("add-transaction", "Dodaj transakcję", ("nowa", "zakup", "sprzedaż", "wpłata", "wypłata")),
            "add",
            add_transaction,
        ),
        PaletteCommand(
            Command("switch-theme", "Przełącz motyw (Jasny/Golden)", ("kolory", "ciemny", "jasny", "golden")),
            "palette",
            switch_theme,
        ),
        PaletteCommand(
            Command("discreet", "Tryb dyskrecji: ukryj lub pokaż kwoty", ("rozmyj", "prywatność")),
            "visibility_off",
            switch_discreet,
        ),
        PaletteCommand(
            Command("refresh-prices", "Odśwież wyceny", ("ceny", "notowania", "kursy")), "refresh", refresh_prices
        ),
    ]
    if switch_user is not None:
        commands.append(
            PaletteCommand(Command("switch-user", "Przełącz użytkownika", ("wyloguj",)), "switch_account", switch_user)
        )
    return commands
