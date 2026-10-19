"""The small "i" icon in a Dashboard card's corner whose hover explains what the card shows and how to read it."""

from nicegui import ui


def info_icon(text: str, name: str) -> None:
    """An "i" icon marked ``info-<name>`` showing ``text`` on hover; blank lines in ``text`` split its paragraphs."""
    with ui.icon("info_outline", size="xs").classes("cursor-help k-muted").mark(f"info-{name}"):
        ui.tooltip(text).classes("max-w-sm text-sm whitespace-pre-line").props('anchor="bottom end" self="top end"')


def card_title(title: str, info: str | None, name: str, classes: str = "text-lg font-medium") -> None:
    """A card's title with, when ``info`` is given, its "i" icon at the right end of the row."""
    with ui.row().classes("w-full items-center justify-between no-wrap gap-2"):
        ui.label(title).classes(classes)
        if info is not None:
            info_icon(info, name)
