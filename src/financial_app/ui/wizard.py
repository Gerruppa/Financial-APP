"""The shared step-by-step window: a ``ui.dialog`` with a "Krok N z M: …" header, one step's body and the
"Wstecz", "Zamknij" and "Dalej" row, "Dalej" held until the step says it is ready.

Its user makes it inside an element that outlives it (CLAUDE.md: NiceGUI deletes a dialog with the element it was
opened in) and keeps the state the steps share; each step draws itself on every ``render``.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from nicegui import ui


@dataclass(frozen=True)
class WizardStep:
    """One step: its title in the header, and the body that draws it and says whether "Dalej" may follow."""

    title: str
    body: Callable[[], bool]


class Wizard:
    """The window and its current step (1 to the number of steps), marked ``<prefix>-wizard``, ``<prefix>-step-<n>``,
    ``<prefix>-back``, ``<prefix>-close`` and ``<prefix>-next``."""

    def __init__(self, prefix: str, steps: Sequence[WizardStep], width: str = "w-[52rem]") -> None:
        self.prefix = prefix
        self.steps = tuple(steps)
        self.step = 1
        self.dialog = ui.dialog()
        with self.dialog, ui.card().classes(f"{width} max-w-full").mark(f"{prefix}-wizard"):
            self.body = ui.column().classes("w-full gap-2")

    def open(self) -> None:
        """Open the window on its first step."""
        self.go(1)
        self.dialog.open()

    def close(self) -> None:
        self.dialog.close()

    def go(self, step: int) -> None:
        self.step = step
        self.render()

    def render(self) -> None:
        """Redraw the current step and the buttons; "Dalej" waits for what the step needs."""
        self.body.clear()
        with self.body:
            title = self.steps[self.step - 1].title
            ui.label(f"Krok {self.step} z {len(self.steps)}: {title}").classes("text-lg font-bold").mark(
                f"{self.prefix}-step-{self.step}"
            )
            ready = self.steps[self.step - 1].body()
            with ui.row().classes("w-full justify-end gap-2"):
                if self.step > 1:
                    ui.button("Wstecz", on_click=lambda: self.go(self.step - 1)).props("flat no-caps").mark(
                        f"{self.prefix}-back"
                    )
                ui.button("Zamknij", on_click=self.close).props("flat no-caps").mark(f"{self.prefix}-close")
                if self.step < len(self.steps):
                    next_button = ui.button("Dalej", on_click=lambda: self.go(self.step + 1)).props("no-caps")
                    next_button.mark(f"{self.prefix}-next")
                    if not ready:
                        next_button.disable()
