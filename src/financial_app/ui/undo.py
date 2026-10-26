"""The undo bar: instead of asking "are you sure?" before a delete, delete at once and offer "Cofnij" for a while."""

from collections.abc import Callable

from nicegui import context, ui

# How long the bar stays; a module value so a test can shorten it
UNDO_SECONDS = 8.0


def offer_undo(message: str, undo: Callable[[], None]) -> None:
    """Show ``message`` with a "Cofnij" button at the foot of the window (``undo-bar``, ``undo-button``) for
    ``UNDO_SECONDS``; the button runs ``undo`` once and closes the bar. It lives in the page's layout, not in the
    dialog the delete came from, so it outlasts that dialog; a newer bar replaces an older one still showing."""
    with context.client.layout:
        for old in [e for e in context.client.layout.descendants() if "k-undo" in e.classes]:
            old.delete()
        with ui.row().classes("k-undo items-center no-wrap gap-2").mark("undo-bar") as bar:
            ui.label(message)

            def run() -> None:
                bar.delete()
                undo()

            # No colour: Quasar would paint it in the Theme's primary, unreadable on the bar's inverted background
            ui.button("Cofnij", color=None, on_click=run).props("flat dense no-caps").mark("undo-button")
            ui.timer(UNDO_SECONDS, bar.delete, once=True)
