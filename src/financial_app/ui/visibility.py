"""Wygląd i widoczność (issue #155): the window's hidden Dashboard elements and tabs, and their section in Ustawienia.

Each element has a switch marked ``ui-visibility-<key>``; the Podstawowy and Pełny View Profiles set them all in one
click, and "Przywróć domyślne" goes back to Pełny. The choice is remembered in ``app_settings`` for every View Scope;
whatever follows it redraws through ``Layout.on_change`` (the shell publishes ``Change.LAYOUT``).
"""

from collections.abc import Callable

from nicegui import ui
from nicegui.events import ValueChangeEventArguments
from sqlalchemy import Engine

from financial_app.domain.ui_visibility import (
    ELEMENTS,
    Profile,
    parse_visibility,
    preset_hidden,
    profile_of,
    visibility_setting,
)
from financial_app.persistence.settings import UI_HIDDEN, load_setting, save_setting

PRESETS = {Profile.BASIC: "basic", Profile.FULL: "full"}


class Layout:
    """A window's hidden elements, by their keys (``domain.ui_visibility``)."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.hidden = parse_visibility(load_setting(engine, UI_HIDDEN))
        self.listeners: list[Callable[[], None]] = []

    def on_change(self, listener: Callable[[], None]) -> None:
        self.listeners.append(listener)

    def shows(self, key: str) -> bool:
        return key not in self.hidden

    def hide(self, hidden: frozenset[str]) -> None:
        """Hide exactly ``hidden`` and remember it, then redraw whatever follows it."""
        self.hidden = hidden
        save_setting(self.engine, UI_HIDDEN, visibility_setting(hidden))
        for listener in self.listeners:
            listener()


class VisibilitySection:
    """The Ustawienia card with the View Profile, its presets and a switch per element, grouped."""

    def __init__(self, layout: Layout) -> None:
        self.layout = layout

    def build(self) -> None:
        with ui.card().classes("w-full").mark("ui-visibility"):
            ui.label("Wygląd i widoczność").classes("text-lg font-bold")
            ui.label(
                "Wybierz, co pokazuje Dashboard i które zakładki są w menu. Ukrycie zmienia tylko widok: obliczenia "
                "i dane zostają bez zmian. Dashboard, Portfolio, Transakcje i Ustawienia są zawsze w menu."
            ).classes("text-sm text-gray-500")
            self.choices()

    @ui.refreshable_method
    def choices(self) -> None:
        with ui.row().classes("w-full items-center gap-2"):
            self.profile()
            ui.space()
            for preset, name in PRESETS.items():
                button = ui.button(preset.value, on_click=lambda p=preset: self._preset(preset_hidden(p)))
                button.props("no-caps flat").mark(f"ui-profile-{name}")
            restore = ui.button("Przywróć domyślne", icon="restart_alt", on_click=lambda: self._preset(frozenset()))
            restore.props("no-caps flat").mark("ui-visibility-restore")
        for group in dict.fromkeys(element.group for element in ELEMENTS):
            ui.label(group).classes("text-sm font-medium mt-2")
            with (
                ui.element("div")
                .classes("grid w-full gap-x-4")
                .style("grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr))")
            ):
                for element in ELEMENTS:
                    if element.group == group:
                        switch = ui.switch(
                            element.label,
                            value=self.layout.shows(element.key),
                            on_change=lambda event, key=element.key: self._switched(key, event),
                        )
                        switch.props("dense").mark(f"ui-visibility-{element.key}")

    @ui.refreshable_method
    def profile(self) -> None:
        text = f"Profil widoku: {profile_of(self.layout.hidden).value}"
        ui.label(text).classes("font-medium").mark("ui-profile")

    def _switched(self, key: str, event: ValueChangeEventArguments[bool]) -> None:
        hidden = self.layout.hidden - {key} if event.value else self.layout.hidden | {key}
        self.layout.hide(hidden)
        self.profile.refresh()

    def _preset(self, hidden: frozenset[str]) -> None:
        self.layout.hide(hidden)
        self.choices.refresh()
