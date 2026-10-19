"""The saying of the day (issue #178): a card beside the Investment Goal and a line at the foot of the menu."""

from datetime import date

from nicegui import ui

from financial_app.domain.sayings import AUTHOR, Saying, saying_of_the_day


def saying_card(day: date) -> None:
    """The Dashboard's saying of ``day`` in a card."""
    saying = saying_of_the_day(day)
    with ui.card().classes("w-full h-full gap-2 justify-center").mark("dashboard-saying"):
        ui.icon("format_quote", size="md").classes("k-accent")
        ui.label(f"„{saying.text}”").classes("text-lg italic")
        _signature(saying)


def menu_saying(day: date) -> None:
    """The menu's saying of ``day``, another one than the Dashboard's."""
    saying = saying_of_the_day(day, menu=True)
    with ui.column().classes("gap-1 px-3 pt-4 text-sm").mark("menu-saying"):
        ui.label(f"„{saying.text}”").classes("italic")
        _signature(saying)


def _signature(saying: Saying) -> None:
    ui.label(f"— {saying.work}, {AUTHOR}").classes("text-xs opacity-70")
