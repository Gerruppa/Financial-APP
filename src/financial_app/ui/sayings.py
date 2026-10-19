"""The saying of the day (issue #178): a line at the foot of the menu."""

from datetime import date

from nicegui import ui

from financial_app.domain.sayings import saying_of_the_day


def menu_saying(day: date) -> None:
    """The saying of ``day`` at the foot of the menu, signed with its work and, when known, its author."""
    saying = saying_of_the_day(day)
    by = f", {saying.author}" if saying.author is not None else ""
    with ui.column().classes("gap-1 px-3 pt-4 text-sm").mark("menu-saying"):
        ui.label(f"„{saying.text}”").classes("italic")
        ui.label(f"— {saying.work}{by}").classes("text-xs opacity-70")
