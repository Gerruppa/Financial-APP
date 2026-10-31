"""An empty section's message, alike on every tab: an icon, the text saying why it is empty, and the button that
does what fills it, rather than a grey line pointing elsewhere."""

from collections.abc import Callable

from nicegui import ui


def empty_state(icon: str, text: str, action: tuple[str, Callable[[], None]] | None = None) -> ui.row:
    """Draw the message and return its row, for the caller's marker; ``action`` is a button's label and click."""
    with ui.row().classes("w-full items-center gap-4 no-wrap py-2") as row:
        with ui.element("div").classes("k-icon shrink-0").style("background:var(--k-highlight); color:var(--k-accent)"):
            ui.icon(icon).classes("text-xl")
        ui.label(text).classes("k-muted grow")
        if action is not None:
            label, on_click = action
            ui.button(label, on_click=on_click).props("outline no-caps").classes("shrink-0")
    return row
