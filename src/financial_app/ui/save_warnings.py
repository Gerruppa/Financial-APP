"""Showing what a save of Transactions warns of (#110), the same way wherever it was saved."""

from nicegui import ui

from financial_app.domain.save_warnings import SaveWarnings


def show_warnings(warnings: SaveWarnings, done: str = "Zapisano", *, unsplit: bool = True) -> None:
    """A warning notification per message; ``done`` and ``unsplit`` as in ``SaveWarnings.messages``."""
    for message in warnings.messages(done, unsplit=unsplit):
        ui.notify(message, type="warning", multi_line=True)
