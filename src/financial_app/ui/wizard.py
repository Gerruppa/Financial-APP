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
    """One step: its title in the header, and the body that draws it and says whether "Dalej" may follow. ``done``
    says whether the job the step points to is done; a window with such steps lists them all above the step."""

    title: str
    body: Callable[[], bool]
    done: Callable[[], bool] | None = None


class Wizard:
    """The window and its current step (1 to the number of steps), marked ``<prefix>-wizard``, ``<prefix>-step-<n>``,
    ``<prefix>-back``, ``<prefix>-close`` and ``<prefix>-next``."""

    def __init__(self, prefix: str, steps: Sequence[WizardStep], width: str = "w-[52rem]") -> None:
        self.prefix = prefix
        self.steps = tuple(steps)
        self.step = 1
        self.next_button: ui.button | None = None
        self.dialog = ui.dialog()
        with self.dialog, ui.card().classes(f"{width} max-w-full").mark(f"{prefix}-wizard"):
            self.body = ui.column().classes("w-full gap-2")

    def open(self, step: int = 1) -> None:
        """Open the window on ``step``, the first by default."""
        self.go(step)
        self.dialog.open()

    def close(self) -> None:
        self.dialog.close()

    def go(self, step: int) -> None:
        self.step = step
        self.render()

    def set_ready(self, ready: bool) -> None:
        """Let "Dalej" follow or hold it without redrawing the step, so a field being typed in keeps the focus."""
        if self.next_button is not None:
            self.next_button.set_enabled(ready)

    def render(self) -> None:
        """Redraw the current step and the buttons; "Dalej" waits for what the step needs."""
        self.next_button = None
        self.body.clear()
        with self.body:
            if any(step.done is not None for step in self.steps):
                self._step_list()
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
                    self.next_button = next_button
                    if not ready:
                        next_button.disable()

    def _step_list(self) -> None:
        """Every step's title, with a tick on those done, each going to its step; marked ``<prefix>-goto-<n>``, a
        done one ``<prefix>-done-<n>`` too."""
        with ui.row().classes("w-full gap-1").mark(f"{self.prefix}-steps"):
            for number, step in enumerate(self.steps, start=1):
                done = step.done is not None and step.done()
                icon = "check_circle" if done else "radio_button_unchecked" if step.done is not None else None
                color = "primary" if number == self.step else "positive" if done else "ink"
                button = ui.button(step.title, on_click=lambda number=number: self.go(number))
                if icon is not None:
                    button.props(f"icon={icon}")
                button.props(f"flat dense no-caps color={color}").classes("text-xs")
                button.mark(f"{self.prefix}-goto-{number}" + (f" {self.prefix}-done-{number}" if done else ""))
