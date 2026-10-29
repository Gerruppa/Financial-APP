"""The undo bar: instead of asking "are you sure?" before a delete, delete at once and offer "Cofnij" for a while.
Its pill, ``action_bar``, also carries the negative cash warning's fix (``ui/save_warnings.py``)."""

from collections.abc import Callable

from nicegui import context, ui

# How long the bar stays; a module value so a test can shorten it
UNDO_SECONDS = 8.0
# The class of a window that keeps the bars while it is open (the covering Deposits window, #267), and how often a
# bar whose time is up checks whether it is still open
HOLDS_BARS = "k-holds-bars"
HOLD_CHECK_SECONDS = 1.0


def offer_undo(message: str, undo: Callable[[], None]) -> None:
    """Show ``message`` with a "Cofnij" button at the foot of the window (``undo-bar``, ``undo-button``) for
    ``UNDO_SECONDS``; the button runs ``undo`` once and closes the bar."""
    action_bar("undo", message, "Cofnij", undo, UNDO_SECONDS)


def action_bar(kind: str, message: str, label: str, action: Callable[[], None], seconds: float) -> None:
    """Show ``message`` with a button ``label`` in the pill ``k-<kind>`` (``<kind>-bar``, ``<kind>-button``) for
    ``seconds``; the button closes the bar and runs ``action`` once. It lives in the page's layout, not in the dialog
    the save came from, so it outlasts that dialog; a newer bar of the kind replaces an older one still showing.
    While a window of class ``HOLDS_BARS`` is open the bar stays past its time, and gets ``seconds`` afresh once it
    closes: "Cofnij" can then undo a delete the window has just covered with Deposits."""
    css = f"k-{kind}"
    with context.client.layout:
        for old in [e for e in context.client.layout.descendants() if css in e.classes]:
            old.delete()
        with ui.row().classes(f"{css} items-center no-wrap gap-2").mark(f"{kind}-bar") as bar:
            ui.label(message)

            def run() -> None:
                bar.delete()
                action()

            # No colour: Quasar would paint it in the Theme's primary, unreadable on the bar's inverted background
            ui.button(label, color=None, on_click=run).props("flat dense no-caps").mark(f"{kind}-button")

            def expire(held: bool = False) -> None:
                with bar:
                    if _holding(bar):
                        ui.timer(HOLD_CHECK_SECONDS, lambda: expire(held=True), once=True)
                    elif held:
                        ui.timer(seconds, expire, once=True)
                    else:
                        bar.delete()

            ui.timer(seconds, expire, once=True)


def _holding(bar: ui.row) -> bool:
    """Whether a window that keeps the bars is open on the bar's page."""
    return any(
        isinstance(element, ui.dialog) and element.value and HOLDS_BARS in element.classes
        for element in bar.client.elements.values()
    )
