"""A Bond Series' rates in Ustawienia > Instrumenty (spec 3.4.1): a summary in its row and a dialog correcting the MF
file's rates by hand, keeping only what differs from the file."""

from collections.abc import Callable
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.bonds import (
    FIXED_RATE_TYPES,
    MONTHLY_TYPES,
    BondSeries,
    RateCorrection,
    correction_of,
)
from financial_app.domain.formatting import format_exact, format_percent
from financial_app.domain.instruments import InstrumentError, parse_optional_number
from financial_app.persistence.bond_series import save_rate_correction
from financial_app.ui.dialogs import movable_dialog


def rates_summary(series: BondSeries) -> str:
    """The Series' first rate and margin for its row in the Instrumenty list, and whether the user corrected them."""
    parts = []
    if series.first_rate is not None:
        parts.append(f"1. okres {format_percent(series.first_rate * 100)}")
    if series.margin is not None and series.bond_type not in FIXED_RATE_TYPES:
        parts.append(f"marża {format_percent(series.margin * 100)}")
    if series.mf is None:
        parts.append("brak w pliku MF")
    if series.correction != RateCorrection():
        parts.append("poprawione ręcznie")
    return " · ".join(parts)


def open_rates_dialog(engine: Engine, series: BondSeries, on_saved: Callable[[], None]) -> None:
    """Edit the Series' margin and the rate of each period; an emptied field returns to the MF file's value."""
    assert series.instrument_id is not None
    instrument_id = series.instrument_id
    dialog = movable_dialog()
    dialog.on("hide", dialog.delete)
    with dialog, ui.card().classes("w-[420px]"):
        ui.label(f"Oprocentowanie serii {series.name}").classes("text-lg font-bold")
        ui.label(
            "Wartości z pliku MF. Popraw tylko te, które się nie zgadzają; puste pole to wartość z pliku."
        ).classes("text-sm k-muted")
        margin = None
        if series.bond_type not in FIXED_RATE_TYPES:
            mf_margin = None if series.mf is None else series.mf.margin
            margin = _rate_input("Marża (%)", series.margin, mf_margin, series.margin_is_corrected)
            margin.mark("bond-margin")
        published = () if series.mf is None else series.mf.rates
        rates = []
        for period, rate in enumerate(series.rates):
            mf_rate = published[period] if period < len(published) else None
            field = _rate_input(_period_name(series, period), rate, mf_rate, series.is_corrected(period))
            rates.append(field.mark(f"bond-rate-{period + 1}"))
        error = ui.label().classes("text-negative").mark("bond-rates-error")

        def save() -> None:
            try:
                typed_margin = None if margin is None else _read(margin.value, "Marża")
                typed = tuple(
                    _read(field.value, f"Oprocentowanie {_period_case(series, period)}")
                    for period, field in enumerate(rates)
                )
            except InstrumentError as exc:
                error.text = str(exc)
                return
            finish(correction_of(series.mf, typed_margin, typed))

        def finish(correction: RateCorrection) -> None:
            save_rate_correction(engine, instrument_id, correction)
            dialog.close()
            on_saved()

        with ui.row().classes("w-full justify-between"):
            restore = ui.button("Przywróć z pliku MF", on_click=lambda: finish(RateCorrection()))
            restore.props("flat no-caps").mark("restore-mf-rates")
            with ui.row():
                ui.button("Anuluj", on_click=dialog.close).props("flat")
                ui.button("Zapisz", on_click=save).mark("save-bond-rates")
    dialog.open()


def _rate_input(label: str, rate: Decimal | None, mf_rate: Decimal | None, corrected: bool) -> ui.input:
    """A percent field holding ``rate``, its hint saying where the value comes from."""
    field = ui.input(label, value="" if rate is None else format_exact((rate * 100).normalize())).classes("w-full")
    if corrected:
        mf = "brak" if mf_rate is None else format_percent(mf_rate * 100)
        hint = f"poprawione; w pliku MF {mf}"
    elif rate is None:
        hint = "MF jeszcze nie podał"
    else:
        hint = "z pliku MF"
    return field.props(f'hint="{hint}"')


def _period_name(series: BondSeries, period: int) -> str:
    if series.bond_type in FIXED_RATE_TYPES:
        return "Cały okres (%)"
    return f"{'Miesiąc' if series.bond_type in MONTHLY_TYPES else 'Rok'} {period + 1} (%)"


def _period_case(series: BondSeries, period: int) -> str:
    """The period for an error message: "w roku 2", "w miesiącu 2"; nothing for a fixed rate."""
    if series.bond_type in FIXED_RATE_TYPES:
        return ""
    return f"{'w miesiącu' if series.bond_type in MONTHLY_TYPES else 'w roku'} {period + 1}"


def _read(text: str | None, name: str) -> Decimal | None:
    """A typed percent as a fraction; empty is ``None``, so the MF file's value stands."""
    number = parse_optional_number(text, name.strip())
    return None if number is None else number / 100
