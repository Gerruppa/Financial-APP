"""The signed-in User's avatar at the right end of the header, with its menu (issue #177, spec 2.1)."""

import webbrowser
from collections.abc import Callable

from nicegui import ui

from financial_app.domain.themes import Theme
from financial_app.domain.users import avatar_colour, initials
from financial_app.ui.theme import ThemeChoice

# Opened in the system browser: in the native window a plain link would replace the app itself.
SUPPORT_URL = "https://buymeacoffee.com/gerruppa"


def build_user_menu(
    pseudonym: str,
    theme: ThemeChoice,
    settings_path: str,
    help_path: str,
    on_switch_user: Callable[[], None] | None,
) -> None:
    """A circle with the pseudonym's initials and the pseudonym beside it (initials alone in a narrow window); clicking
    opens the menu: the pseudonym, Ustawienia, the other Theme, Pomoc, "Wesprzyj projekt" (the Buy Me a Coffee page)
    and, with ``on_switch_user``, "Przełącz użytkownika" (the demo has no login screen to return to)."""
    other = Theme.LIGHT if theme.theme is Theme.GOLDEN else Theme.GOLDEN
    with ui.button().props('flat no-caps color=ink aria-label="Menu użytkownika"').classes("k-user").mark("user-menu"):
        ui.label(initials(pseudonym)).classes("k-avatar").style(f"background:{avatar_colour(pseudonym)}").mark(
            "user-avatar"
        )
        ui.label(pseudonym).classes("gt-sm q-ml-sm").mark("user-name")
        with ui.menu().props("auto-close"):
            ui.menu_item(pseudonym).props("disable").mark("user-menu-name")
            ui.menu_item("Ustawienia", on_click=lambda: ui.navigate.to(settings_path)).mark("menu-settings")
            ui.menu_item(f"Motyw: {other.label}", on_click=lambda: theme.choose(other)).mark("theme-toggle")
            ui.menu_item("Pomoc", on_click=lambda: ui.navigate.to(help_path)).mark("menu-help")
            ui.menu_item("Wesprzyj projekt", on_click=lambda: webbrowser.open(SUPPORT_URL)).mark("menu-support")
            if on_switch_user is not None:
                ui.separator()
                ui.menu_item("Przełącz użytkownika", on_click=on_switch_user).mark("switch-user")
