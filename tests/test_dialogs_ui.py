"""Esc closes the movable dialogs, the topmost first."""

from nicegui import ui
from nicegui.testing import user_simulation

from financial_app.ui.dialogs import close_topmost_dialog, install_movable_dialogs, movable_dialog


async def test_escape_closes_the_topmost_dialog_first() -> None:
    opened: list[ui.dialog] = []

    def page() -> None:
        install_movable_dialogs()
        for name in ("lower", "upper"):
            with movable_dialog() as dialog, ui.card():
                ui.label(name)
            dialog.open()
            opened.append(dialog)

    async with user_simulation(page) as user:
        await user.open("/")
        lower, upper = opened
        assert user.client is not None

        with user.client:
            close_topmost_dialog()
        assert (lower.value, upper.value) == (True, False)

        with user.client:
            close_topmost_dialog()
        assert (lower.value, upper.value) == (False, False)
