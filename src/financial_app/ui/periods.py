"""The period selector shared by every chart and result (spec section 5 and 6.1), remembered in ``app_settings``.

Presets 1M to "Od początku", or "Własny" with the days typed in; the range it gives is shown beside it, clipped to the
first Transaction. Whatever follows the period redraws through ``PeriodChoice.on_change``.
"""

from collections.abc import Callable
from datetime import date

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_date, parse_date
from financial_app.domain.periods import Period, PeriodError, PeriodPreset, parse_period, period_dates, period_setting
from financial_app.persistence.settings import PERIOD, load_setting, save_setting
from financial_app.persistence.transactions import list_transactions


class PeriodChoice:
    """A window's period; ``today`` is injectable for tests."""

    def __init__(self, engine: Engine, today: Callable[[], date] = date.today) -> None:
        self.engine = engine
        self.today = today
        self.period = parse_period(load_setting(engine, PERIOD))
        self.listeners: list[Callable[[], None]] = []

    def on_change(self, listener: Callable[[], None]) -> None:
        self.listeners.append(listener)

    def choose(self, period: Period) -> None:
        self.period = period
        save_setting(self.engine, PERIOD, period_setting(period))
        for listener in self.listeners:
            listener()

    def dates(self) -> tuple[date, date]:
        """The "from" and "to" days of the period, clipped to the first Transaction."""
        transactions = list_transactions(self.engine)
        inception = min((t.date for t in transactions), default=None)
        return period_dates(self.period, self.today(), inception)


def period_selector(choice: PeriodChoice) -> None:
    """The presets as buttons, the custom days under "Własny", and the range the period gives."""

    def preset_chosen(preset: PeriodPreset) -> None:
        custom.set_visibility(preset is PeriodPreset.CUSTOM)
        shown_presets.refresh(preset)
        if preset is not PeriodPreset.CUSTOM:
            choice.choose(Period(preset))
            shown_range.refresh()

    def apply_custom() -> None:
        try:
            first_day, last_day = parse_date(first.value), parse_date(last.value)
        except ValueError:
            ui.notify("Podaj daty w formacie DD.MM.RRRR.", type="warning")
            return
        try:
            period = Period(PeriodPreset.CUSTOM, first_day, last_day)
        except PeriodError as error:
            ui.notify(str(error), type="warning")
            return
        choice.choose(period)
        shown_range.refresh()

    @ui.refreshable
    def shown_presets(chosen: PeriodPreset) -> None:
        with ui.button_group().props("flat"):
            for preset in PeriodPreset:
                button = ui.button(preset.label, on_click=lambda p=preset: preset_chosen(p)).props("no-caps dense")
                button.props("unelevated color=indigo" if preset is chosen else "flat color=grey-8")
                button.classes("px-2").mark(f"period-{preset}")

    @ui.refreshable
    def shown_range() -> None:
        first_day, last_day = choice.dates()
        ui.label(f"{format_date(first_day)} – {format_date(last_day)}").classes("text-sm text-gray-600").mark(
            "period-range"
        )

    current = choice.period
    with ui.row().classes("items-center gap-4").mark("period-selector"):
        shown_presets(current.preset)
        shown_range()
    with ui.row().classes("items-center gap-2").mark("period-custom") as custom:
        first = ui.input("Od", value=format_date(current.first) if current.first else "").props("dense").classes("w-32")
        first.mark("period-from")
        last = ui.input("Do", value=format_date(current.last) if current.last else "").props("dense").classes("w-32")
        last.mark("period-to")
        ui.button("Zastosuj", on_click=apply_custom).props("outline dense")
    custom.set_visibility(current.preset is PeriodPreset.CUSTOM)
