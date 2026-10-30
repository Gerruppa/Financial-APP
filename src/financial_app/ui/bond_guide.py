"""The bond help window (issue #272), opened from the "+" dialog's bond mode and from the Rollover dialog: what each
series code means and how it pays interest, the chosen Series' interest periods with the rate the app takes for each
and its source, what a Rollover does, and what to compare with the broker's statement afterwards."""

from datetime import date

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.bond_guide import guide_periods
from financial_app.domain.bonds import COUPON_TYPES, MONTHLY_TYPES, BondSeries, BondType
from financial_app.domain.formatting import format_date, format_percent
from financial_app.persistence.bond_data import load_series_terms
from financial_app.persistence.bond_series import load_bond_data
from financial_app.ui.dialogs import movable_dialog

# What each series code means and how it pays interest, in the order the "+" dialog offers them
TYPE_HELP = {
    BondType.OTS: "3 miesiące, stałe oprocentowanie; odsetki wypłacane z kapitałem przy wykupie.",
    BondType.ROR: "1 rok; 1. miesiąc stały, potem stopa referencyjna NBP + marża; odsetki wypłacane co miesiąc.",
    BondType.DOR: "2 lata; 1. miesiąc stały, potem stopa referencyjna NBP + marża; odsetki wypłacane co miesiąc.",
    BondType.TOS: "3 lata, stałe oprocentowanie; odsetki kapitalizowane co rok, wypłacane przy wykupie.",
    BondType.COI: "4 lata; 1. rok stały, potem inflacja + marża; odsetki wypłacane co rok.",
    BondType.EDO: "10 lat; 1. rok stały, potem inflacja + marża; odsetki kapitalizowane co rok, wypłacane z wykupem.",
    BondType.ROS: "6 lat, rodzinne (dla pobierających 800+); 1. rok stały, potem inflacja + marża; jak EDO.",
    BondType.ROD: "12 lat, rodzinne (dla pobierających 800+); 1. rok stały, potem inflacja + marża; jak EDO.",
}

ROLLOVER_HELP = (
    "Zamiana to wykup starych obligacji w dniu ich wykupu i zakup nowych za uzyskane pieniądze.",
    "Data zakupu nowej serii to dzień wykupu starej; od niej liczą się okresy odsetkowe nowej serii.",
    "Cena jednej nowej obligacji to cena zamiany z pliku MF (zwykle 99,90 zł), nie 100 zł.",
    "Aplikacja zapisuje dwie transakcje: sprzedaż starej partii (z podatkiem Belki, bez niego na IKE i IKZE) "
    "i zakup nowej serii; stara seria znika z portfela.",
    "Zamianę wpisaną ręcznie przyciskiem „+” oznacz polem „z rolowania”. Obligacji rodzinnych nie kupuje się "
    "w zamianie.",
)

CHECKLIST = (
    "Seria i liczba obligacji.",
    "Data zakupu: od niej liczą się okresy odsetkowe i rocznice.",
    "Cena jednej obligacji: 100 zł albo cena zamiany.",
    "Oprocentowanie 1. okresu i marża: inne poprawisz w Ustawienia > Instrumenty.",
    "Odsetki COI, ROR i DOR: kwota netto i podatek każdej wypłaty.",
    "Przy wykupie: kwota netto i podatek Belki (na IKE i IKZE bez podatku).",
)

# Where a period's rate may come from, explained under the periods
SOURCES_HELP = (
    "„z pliku MF”: stawka ogłoszona przez Ministerstwo Finansów; „poprawione ręcznie”: Twoja poprawka; "
    "„szacowana” i „prognoza”: wyliczona z inflacji GUS albo stopy NBP, dopóki MF jej nie poda."
)


def open_bond_guide(engine: Engine, series_name: str | None, purchase_day: date | None) -> None:
    """Open the help window; with ``series_name`` and ``purchase_day`` it lists that Series' periods for a bond bought
    that day, with the user's rate corrections."""
    dialog = movable_dialog()
    dialog.on("hide", dialog.delete)
    with dialog, ui.card().classes("w-[600px] max-w-[95vw] max-h-[85vh] overflow-auto gap-2").mark("bond-guide"):
        with ui.row().classes("w-full items-start no-wrap"):
            ui.label("Obligacje skarbowe: serie, oprocentowanie, zamiana").classes("text-lg font-bold grow")
            ui.button(icon="close", on_click=dialog.close).props('flat round dense aria-label="Zamknij pomoc"')
        _periods(engine, series_name, purchase_day)
        ui.label("Rodzaje obligacji").classes("font-bold mt-2")
        for bond_type, text in TYPE_HELP.items():
            ui.label(f"{bond_type}: {text}").classes("text-sm")
        ui.label("Zamiana (rolowanie)").classes("font-bold mt-2")
        for text in ROLLOVER_HELP:
            ui.label(f"• {text}").classes("text-sm")
        ui.label("Co sprawdzić z wyciągiem").classes("font-bold mt-2")
        for text in CHECKLIST:
            ui.label(f"☐ {text}").classes("text-sm")
    dialog.open()


def _periods(engine: Engine, series_name: str | None, purchase_day: date | None) -> None:
    """The Series' periods, each with its dates, rate and the rate's source."""
    if series_name is None or purchase_day is None:
        ui.label("Podaj datę zakupu, by zobaczyć okresy odsetkowe serii.").classes("text-sm k-muted")
        return
    data = load_bond_data(engine)
    series = next((s for s in data.series.values() if s.name == series_name), None)
    if series is None:
        series = BondSeries(None, series_name, load_series_terms(engine).get(series_name))
    bond_type = series.bond_type
    ui.label(f"Okresy odsetkowe serii {series.name}").classes("font-bold")
    ui.label(f"{bond_type}: {TYPE_HELP[bond_type]}").classes("text-sm k-muted")
    unit = "Miesiąc" if bond_type in MONTHLY_TYPES else "Okres" if bond_type is BondType.OTS else "Rok"
    with ui.column().classes("w-full gap-0").mark("bond-guide-periods"):
        for period in guide_periods(series, purchase_day, data.cpi, data.reference):
            rate = "?" if period.rate is None else format_percent(period.rate * 100)
            dates = f"{format_date(period.start)}–{format_date(period.end)}"
            ui.label(f"{unit} {period.number} · {dates} · {rate} · {period.source}").classes("text-sm")
    ui.label(SOURCES_HELP).classes("text-xs k-muted")
    if bond_type in COUPON_TYPES:
        ui.label(
            "Odsetki każdego okresu prócz ostatniego pojawią się w „Do zatwierdzenia” w Dochodzie stałym."
        ).classes("text-xs k-muted")
