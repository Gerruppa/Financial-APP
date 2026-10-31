"""A tab's header, one for every tab: its title, an optional muted line under it, and on the right the tab's actions
(the report's year and export buttons, a grouping), so that every tab starts alike."""

from nicegui import ui


def page_header(title: str, subtitle: str | None = None) -> ui.row:
    """Draw the title (``page-title``) and ``subtitle``, and return the row of actions on the right, which wraps under
    the title when the window is narrow: ``with page_header("Wyniki"):`` draws the actions in it."""
    with ui.row().classes("w-full max-w-screen-2xl items-end justify-between gap-x-6 gap-y-2"):
        with ui.column().classes("gap-0"):
            ui.label(title).classes("text-2xl font-bold").mark("page-title")
            if subtitle:
                ui.label(subtitle).classes("text-sm k-muted")
        return ui.row().classes("items-center gap-2")
