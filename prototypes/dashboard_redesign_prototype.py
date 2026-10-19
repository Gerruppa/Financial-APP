"""PROTOTYP, do wyrzucenia: jak ma wyglądać nowy Dashboard i motyw „golden”.

Trzy układy Dashboardu (``?variant=A|B|C``) w dwóch motywach (``?theme=jasny|golden``), przełączane paskiem na dole
ekranu albo strzałkami ← →. A to propozycja z makiety, B zwarty panel, C raport z kolumną liczb.

Uruchomienie: .venv/Scripts/python.exe prototypes/dashboard_redesign_prototype.py, potem http://127.0.0.1:8090

Dane: świeża baza demo (``seed_demo_data``) w %TEMP%\\KAPITA-prototype, nigdy prawdziwa. Kafelki i konta liczy
prawdziwy ``todays_dashboard``. Historia wykresu idzie przez prawdziwy ``daily_history``, ale ceny dzienne są
ZMYŚLONE (losowy spacer w pamięci), bo demo nie ma notowań. Cel inwestycyjny to atrapa. Nic się nie zapisuje.
"""

import os
import random
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from nicegui import ui

from financial_app import __version__
from financial_app.domain.formatting import format_date, format_percent, format_pln
from financial_app.domain.portfolio_history import DayValue, HistoryPrice, daily_history
from financial_app.persistence.db import init_db
from financial_app.persistence.paths import DATA_DIR_ENV, database_path
from financial_app.sources.dashboard import todays_dashboard
from financial_app.sources.demo_data import seed_demo_data
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory

LOGO = Path(__file__).parents[1] / "src" / "financial_app" / "ui" / "assets" / "kapita.png"
VARIANTS = {"A": "Propozycja z makiety", "B": "Zwarty panel", "C": "Raport z kolumną liczb"}
THEMES = {"jasny": "Jasny", "golden": "Golden"}
GOAL = Decimal(1_500_000)  # atrapa celu inwestycyjnego

# ---------------------------------------------------------------------------------------------------------- dane demo


def _load() -> dict[str, object]:
    os.environ[DATA_DIR_ENV] = str(Path(tempfile.gettempdir()) / "KAPITA-prototype")
    database_path().unlink(missing_ok=True)
    engine = init_db(database_path())
    today = date.today()
    seed_demo_data(engine, today)
    rates = NbpRates(engine)
    inputs = PortfolioHistory(engine, QuoteHistory(engine), rates, lambda: today).inputs()
    assert inputs is not None
    # ZMYŚLONE ceny dzienne: od ceny pierwszego zakupu do dzisiejszej Ceny Ręcznej, z szumem
    rng = random.Random(7)
    prices: dict[int, list[HistoryPrice]] = {}
    for instrument_id, instrument in inputs.instruments.items():
        buys = [t for t in inputs.transactions if t.instrument_id == instrument_id and t.price is not None]
        if not buys or instrument.manual_price is None:
            continue
        start, begin, end = buys[0].date, float(buys[0].price), float(instrument.manual_price)
        n = (today - start).days
        walk, level = [], 0.0
        for _ in range(n + 1):
            level += rng.gauss(0, 0.012)
            walk.append(level)
        prices[instrument_id] = [
            HistoryPrice(
                start + timedelta(days=i),
                Decimal(
                    str(round((begin + (end - begin) * i / max(n, 1)) * (1 + walk[i] - walk[-1] * i / max(n, 1)), 2))
                ),
                "PLN",
            )
            for i in range(n + 1)
        ]
    days = daily_history(
        inputs.transactions, inputs.instruments, prices, inputs.rates, inputs.first, today, inputs.bonds,
        inputs.accruals,
    )  # fmt: skip
    board = todays_dashboard(engine, rates, None, days, (inputs.first, today)).board
    return {"board": board, "days": days, "today": today}


DATA = _load()

# ------------------------------------------------------------------------------------------------------------ motywy

MOUNTAINS = (
    "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 800 300' "
    "preserveAspectRatio='none'><defs><linearGradient id='g' x1='0' y1='0' x2='0' y2='1'>"
    "<stop offset='0' stop-color='%23d4af37' stop-opacity='0.3'/><stop offset='1' stop-color='%23000' "
    "stop-opacity='0'/></linearGradient></defs><path fill='url(%23g)' d='M0 300 L0 210 L90 150 L150 185 L260 60 "
    "L330 130 L390 95 L470 170 L560 80 L640 140 L720 110 L800 160 L800 300 Z'/><path fill='%23000' "
    "fill-opacity='0.55' d='M0 300 L0 250 L120 200 L210 240 L330 170 L450 235 L580 190 L700 230 L800 210 L800 300 "
    "Z'/></svg>\")"
)

CSS = """
.theme-jasny { --bg:#f4f6fa; --side:#0f1b33; --side-text:#cbd5e1; --side-active:#1e2b48; --card:#ffffff;
  --border:#e5e9f0; --text:#0f172a; --muted:#64748b; --accent:#2563eb; --accent-text:#fff; --pos:#16a34a;
  --neg:#dc2626; --hero:#0f172a; --chip:#f1f5f9; --input:#eef2f7; }
.theme-golden { --bg:#0b0b0c; --side:#0e0e0f; --side-text:#d4d4d4; --side-active:#2a2416; --card:#141414;
  --border:rgba(212,175,55,.22); --text:#f2f2f2; --muted:#a3a3a3; --accent:#d4af37; --accent-text:#111;
  --pos:#22c55e; --neg:#ef4444; --hero:#e8c766; --chip:#1c1c1c; --input:#161616; }
body { background:var(--bg); color:var(--text); }
.theme-golden body, body.theme-golden { background:var(--bg) MOUNTAINS no-repeat right top / 70% 260px; }
.k-side { background:var(--side); color:var(--side-text); }
.theme-golden .k-side { background:var(--side) MOUNTAINS no-repeat bottom / 100% 320px;
  border-right:1px solid var(--border); }
.k-item { color:var(--side-text); border-radius:10px; }
.k-item.active { background:var(--side-active); color:#fff; box-shadow: inset 3px 0 0 var(--accent); }
.theme-golden .k-item.active { color:var(--accent); }
.k-card { background:var(--card); border:1px solid var(--border); border-radius:14px;
  box-shadow:0 1px 3px rgba(15,23,42,.06); }
.theme-golden .k-card { background:linear-gradient(180deg,#171717,#101010); }
.k-muted { color:var(--muted); }
.k-pos { color:var(--pos); } .k-neg { color:var(--neg); }
.k-hero { color:var(--hero); }
.k-accent { color:var(--accent); }
.k-btn { background:var(--chip); color:var(--text) !important; border:1px solid var(--border); border-radius:8px; }
.k-btn.on { background:var(--accent) !important; color:var(--accent-text) !important; border-color:var(--accent); }
.k-btn.on .q-btn__content, .k-btn.on .q-icon { color:var(--accent-text) !important; }
.q-circular-progress__track { color:var(--chip) !important; opacity:1 !important; }
.q-linear-progress__track { background:var(--chip) !important; opacity:1 !important; }
.theme-golden { --chip:#262626; }
.k-input { background:var(--input); border:1px solid var(--border); border-radius:10px; color:var(--muted); }
.k-ico { width:44px; height:44px; border-radius:999px; display:flex; align-items:center; justify-content:center; }
.theme-golden .k-ico { background:rgba(212,175,55,.12) !important; color:var(--accent) !important; }
.k-quote { font-style:italic; }
.k-proto-bar { background:#111827; color:#fff; border-radius:999px; box-shadow:0 8px 30px rgba(0,0,0,.35);
  border:2px dashed #f472b6; }
""".replace("MOUNTAINS", MOUNTAINS)

TILE_COLOURS = {  # tło i kolor ikony w motywie jasnym
    "net-deposits": ("#dcfce7", "#16a34a"),
    "value": ("#ede9fe", "#6d28d9"),
    "open-positions": ("#dbeafe", "#2563eb"),
    "cash": ("#fef3c7", "#d97706"),
    "unrealized": ("#dcfce7", "#16a34a"),
    "realized": ("#dcfce7", "#16a34a"),
    "dividends": ("#dbeafe", "#2563eb"),
    "costs": ("#fee2e2", "#dc2626"),
    "xirr": ("#dbeafe", "#2563eb"),
}
ACCOUNT_COLOURS = ["#f97316", "#2563eb", "#eab308", "#7c3aed", "#e11d48"]


def _chart_colours(theme: str) -> dict[str, str]:
    if theme == "golden":
        return {"line": "#d4af37", "area": "rgba(212,175,55,.28)", "grid": "#2a2a2a", "text": "#a3a3a3"}
    return {"line": "#16a34a", "area": "rgba(22,163,74,.22)", "grid": "#eef2f7", "text": "#64748b"}


# ------------------------------------------------------------------------------------------------------------ liczby


def _f(value: Decimal) -> float:
    return float(value)


def _days() -> list[DayValue]:
    return DATA["days"]  # type: ignore[return-value]


def _change() -> tuple[Decimal, Decimal]:
    days = _days()
    today, yesterday = days[-1].total, days[-2].total
    return today - yesterday, (today - yesterday) / yesterday * 100 if yesterday else Decimal(0)


def _tiles() -> list[tuple[str, str, str, str, str | None]]:
    """(klucz, tytuł, ikona, wartość, podpis) prawdziwych kafelków Dashboardu."""
    t = DATA["board"].totals  # type: ignore[attr-defined]
    share = t.cash / t.value * 100 if t.value else Decimal(0)
    unreal_pct = t.unrealized / (t.open_positions - t.unrealized) * 100 if t.open_positions else Decimal(0)
    return [
        ("net-deposits", "Wpłaty netto", "account_balance_wallet", format_pln(t.net_deposits or 0), None),
        ("value", "Wartość konta", "pie_chart", format_pln(t.value), None),
        ("open-positions", "Otwarte pozycje", "storage", format_pln(t.open_positions), None),
        ("cash", "Gotówka", "account_balance", format_pln(t.cash), f"{format_percent(share)} portfela"),
        ("unrealized", "Niezrealizowany zysk", "trending_up", format_pln(t.unrealized, signed=True),
         format_percent(unreal_pct, signed=True)),
        ("realized", "Zrealizowany zysk", "bar_chart", format_pln(t.realized, signed=True), None),
        ("dividends", "Dywidendy i odsetki", "paid", format_pln(t.dividends), None),
        ("costs", "Prowizje i koszty", "sell", format_pln(t.costs),
         f"{format_percent(t.costs / t.value * 100 if t.value else 0)} portfela"),
        ("xirr", "XIRR", "percent", "—" if t.xirr is None else format_percent(t.xirr * 100), None),
    ]  # fmt: skip


def _sign_class(text: str) -> str:
    return "k-neg" if text.startswith(("-", "−")) else "k-pos"


# -------------------------------------------------------------------------------------------------- wspólne elementy

MENU = [
    ("Dashboard", "home"), ("Wyniki", "insights"), ("Portfolio", "pie_chart"), ("Transakcje", "receipt_long"),
    ("Strategie inwestycyjne", "track_changes"), ("Dochód stały", "savings"), ("Multi-asset", "donut_large"),
    ("Benchmarki", "bar_chart"), ("Podsumowanie sprzedaży", "sell"), ("Dochód pasywny", "payments"),
]  # fmt: skip


def _sidebar() -> None:
    with ui.left_drawer(value=True).props("width=250 bordered=false").classes("k-side p-0"):
        with ui.column().classes("w-full h-full p-4 gap-1 no-wrap"):
            with ui.row().classes("items-center gap-3 mb-6 px-2"):
                ui.image(LOGO).classes("w-10 h-10 bg-white rounded-lg")
                with ui.column().classes("gap-0"):
                    ui.label("KAPITA").classes("text-xl font-bold tracking-widest text-white")
                    ui.label(__version__).classes("text-xs opacity-60")
            for i, (label, icon) in enumerate(MENU):
                with ui.row().classes(
                    f"k-item {'active' if i == 0 else ''} items-center gap-3 px-3 py-2 w-full no-wrap"
                ):
                    ui.icon(icon).classes("text-xl")
                    ui.label(label).classes("text-sm")
            ui.separator().classes("my-3 opacity-20")
            for label, icon in (("Ustawienia", "settings"), ("Pomoc", "help")):
                with ui.row().classes("k-item items-center gap-3 px-3 py-2 w-full"):
                    ui.icon(icon).classes("text-xl")
                    ui.label(label).classes("text-sm")
            ui.space()
            ui.label("„Dyscyplina buduje wolność finansową.”").classes("k-quote text-sm opacity-80 px-2")


def _header(variant: str, theme: str) -> None:
    other = "jasny" if theme == "golden" else "golden"
    with ui.row().classes("w-full items-center gap-4 px-6 py-3").style("border-bottom:1px solid var(--border)"):
        with ui.row().classes("k-input items-center gap-2 px-3 py-2 w-96"):
            ui.icon("search").classes("k-muted")
            ui.label("Szukaj… (np. instrument, ticker, transakcja)").classes("text-sm")
        ui.space()
        ui.icon("notifications_none").classes("text-2xl k-muted")
        toggle = ui.button(
            icon="light_mode" if theme == "golden" else "dark_mode",
            on_click=lambda: ui.navigate.to(f"/?variant={variant}&theme={other}"),
        )
        toggle.props("flat round").classes("k-accent")
        toggle.tooltip(f"Motyw: {THEMES[other]} (w aplikacji: Ustawienia → Wygląd)")


def _title_row(subtitle: bool = True) -> None:
    days = _days()
    with ui.row().classes("w-full items-end gap-4"):
        with ui.column().classes("gap-0"):
            ui.label("Dashboard").classes("text-3xl font-bold")
            if subtitle:
                ui.label("Przegląd Twoich inwestycji i wyników portfela").classes("k-muted")
        ui.space()
        ui.label(f"Wyceny: {format_date(days[-1].day)}").classes("text-sm k-muted")
        ui.button(icon="refresh").props("flat round").classes("k-btn")
        with ui.row().classes("k-btn items-center gap-2 px-3 py-2 text-sm"):
            ui.icon("event")
            ui.label(f"{format_date(days[0].day)} – {format_date(days[-1].day)}")


PERIODS = {"1M": 30, "3M": 91, "YTD": None, "1R": 365, "Od początku": 0}


def _value_chart(theme: str, height: str = "h-64") -> None:
    colours = _chart_colours(theme)
    state = {"period": "Od początku"}

    @ui.refreshable
    def body() -> None:
        days = _days()
        span = PERIODS[state["period"]]
        if span is None:
            days = [d for d in days if d.day.year == days[-1].day.year]
        elif span:
            days = days[-span:]
        with ui.row().classes("gap-1 justify-end w-full"):
            for name in PERIODS:
                ui.button(name, on_click=lambda n=name: (state.update(period=n), body.refresh())).props(
                    "flat dense no-caps").classes(f"k-btn px-3 {'on' if name == state['period'] else ''}")  # fmt: skip
        ui.echart({
            "grid": {"left": 8, "right": 56, "top": 10, "bottom": 24},
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": [format_date(d.day) for d in days], "boundaryGap": False,
                      "axisLine": {"show": False}, "axisTick": {"show": False},
                      "axisLabel": {"color": colours["text"]}},
            "yAxis": {"type": "value", "position": "right", "scale": True,
                      "splitLine": {"lineStyle": {"color": colours["grid"]}}, "axisLabel": {"color": colours["text"]}},
            "series": [{"type": "line", "data": [round(_f(d.total), 2) for d in days], "showSymbol": False,
                        "smooth": 0.2, "lineStyle": {"color": colours["line"], "width": 2},
                        "areaStyle": {"color": {"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1, "colorStops": [
                            {"offset": 0, "color": colours["area"]}, {"offset": 1, "color": "rgba(0,0,0,0)"}]}}}],
        }).classes(f"w-full {height}")  # fmt: skip

    body()


def _hero_value(size: str = "text-5xl") -> None:
    value = DATA["board"].totals.value  # type: ignore[attr-defined]
    change, pct = _change()
    ui.label("Wartość portfela").classes("k-muted")
    ui.label(format_pln(value)).classes(f"{size} font-bold k-hero")
    text = f"{format_pln(change, signed=True)} ({format_percent(pct, signed=True)})"
    with ui.row().classes("items-center gap-1"):
        ui.icon("arrow_drop_up" if change >= 0 else "arrow_drop_down").classes(f"text-3xl {_sign_class(text)}")
        ui.label(text).classes(f"text-lg font-medium {_sign_class(text)}")
    ui.label(f"Zmiana od {format_date(_days()[-2].day)}").classes("text-sm k-muted")


def _icon(key: str, icon: str) -> None:
    bg, fg = TILE_COLOURS.get(key, ("#e2e8f0", "#334155"))
    with ui.element("div").classes("k-ico shrink-0").style(f"background:{bg}; color:{fg}"):
        ui.icon(icon).classes("text-2xl")


def _sparkline(values: list[float], theme: str) -> None:
    up = values[-1] >= values[0]
    colour = ("#22c55e" if up else "#ef4444") if theme == "golden" else ("#16a34a" if up else "#dc2626")
    ui.echart({
        "grid": {"left": 0, "right": 0, "top": 2, "bottom": 2}, "xAxis": {"type": "category", "show": False},
        "yAxis": {"type": "value", "show": False, "scale": True},
        "series": [{"type": "line", "data": values, "showSymbol": False, "lineStyle": {"color": colour, "width": 1.5},
                    "areaStyle": {"color": colour, "opacity": 0.12}}],
    }).classes("w-28 h-10")  # fmt: skip


def _accounts() -> list[tuple[str, Decimal, Decimal, list[float]]]:
    """(nazwa, wartość, zmiana 30 dni w %, przebieg 90 dni) każdego Konta."""
    days = _days()
    rows = []
    for row in DATA["board"].accounts:  # type: ignore[attr-defined]
        series = [_f(d.accounts.get(row.account.id, Decimal(0))) for d in days[-90:]]
        base = days[-31].accounts.get(row.account.id, Decimal(0))
        now = row.totals.value
        rows.append((row.account.name, now, (now - base) / base * 100 if base else Decimal(0), series))
    return rows


def _goal(compact: bool = False) -> None:
    value = DATA["board"].totals.value  # type: ignore[attr-defined]
    pct = value / GOAL * 100
    with ui.row().classes("items-center gap-3"):
        ui.icon("track_changes").classes("text-2xl k-accent")
        ui.label("Cel inwestycyjny").classes("text-lg font-semibold")
        ui.label("(atrapa)").classes("text-xs k-muted")
    with ui.row().classes("w-full items-center gap-6 no-wrap"):
        if not compact:
            ui.circular_progress(value=float(pct / 100), show_value=False, size="96px").props(
                "thickness=0.18").classes("k-accent")  # fmt: skip
        with ui.column().classes("grow gap-1"):
            ui.label(f"Cel: {format_pln(GOAL)}").classes("font-semibold")
            ui.label(f"{format_pln(value)} z {format_pln(GOAL)} · {format_percent(pct, 1)}").classes("text-sm k-muted")
            ui.linear_progress(value=float(pct / 100), show_value=False, size="10px").props(
                "rounded").classes("k-accent")  # fmt: skip
            ui.label("Prognoza: cel w 09.2053 przy wpłatach 1 500,00 zł miesięcznie").classes("text-xs k-muted")


# ---------------------------------------------------------------------------------------------------------- wariant A


def variant_a(theme: str) -> None:
    """A: propozycja z makiety: duża karta z wartością i wykresem, kafelki z ikonami, cel, konta jako karty."""
    _title_row()
    with ui.row().classes("k-card w-full p-6 gap-6 no-wrap items-center"):
        with ui.column().classes("gap-1 w-80 shrink-0"):
            _hero_value()
        with ui.column().classes("grow gap-2"):
            _value_chart(theme)
    tiles = _tiles()
    for chunk, cols in ((tiles[:5], 5), (tiles[5:], 4)):
        with ui.element("div").classes(f"grid grid-cols-{cols} gap-4 w-full"):
            for key, title, icon, value, note in chunk:
                with ui.row().classes("k-card p-4 gap-3 no-wrap items-start"):
                    _icon(key, icon)
                    with ui.column().classes("gap-0 grow"):
                        with ui.row().classes("w-full items-center no-wrap"):
                            ui.label(title).classes("text-sm k-muted grow")
                            ui.icon("info_outline").classes("k-muted")
                        ui.label(value).classes("text-xl font-semibold")
                        if note:
                            ui.label(note).classes(f"text-xs {_sign_class(note) if note[0] in '+-−' else 'k-muted'}")
    with ui.row().classes("w-full gap-4 no-wrap"):
        with ui.column().classes("k-card p-6 grow gap-3"):
            _goal()
        with ui.column().classes("k-card p-6 w-72 items-center justify-center gap-2"):
            ui.icon("eco").classes("text-4xl k-accent")
            ui.label("„Małe kroki, wielkie rezultaty.”").classes("k-quote text-xl text-center")
            ui.label("— KAPITA").classes("text-xs k-muted")
    with ui.column().classes("k-card p-6 w-full gap-4"):
        with ui.row().classes("w-full items-center"):
            ui.label("Twoje konta i aktywa").classes("text-lg font-semibold grow")
            ui.button("Karty", icon="view_module").props("flat dense no-caps").classes("k-btn on px-3")
            ui.button("Tabela", icon="table_rows").props("flat dense no-caps").classes("k-btn px-3")
            ui.button("Dodaj konto", icon="add").props("flat dense no-caps").classes("k-btn px-3 k-accent")
        grid = ui.element("div").classes("grid gap-4 w-full")
        with grid.style("grid-template-columns: repeat(auto-fill, minmax(18rem, 1fr))"):
            for i, (name, value, pct, series) in enumerate(_accounts()):
                with ui.column().classes("k-card p-4 gap-1"):
                    with ui.row().classes("items-center gap-3 no-wrap w-full"):
                        with ui.element("div").classes("k-ico").style(f"background:{ACCOUNT_COLOURS[i]};color:#fff"):
                            ui.icon("account_balance").classes("text-xl")
                        ui.label(name).classes("text-sm grow")
                        ui.icon("chevron_right").classes("k-muted")
                    with ui.row().classes("w-full items-end no-wrap"):
                        with ui.column().classes("gap-0 grow"):
                            ui.label(format_pln(value)).classes("font-semibold")
                            text = format_percent(pct, signed=True)
                            ui.label(f"{text} (30 dni)").classes(f"text-sm {_sign_class(text)}")
                        _sparkline(series, theme)


# ---------------------------------------------------------------------------------------------------------- wariant B


def variant_b(theme: str) -> None:
    """B: zwarty panel: pasek czterech najważniejszych liczb, wykres obok pogrupowanych list, konta jako tabela."""
    _title_row(subtitle=False)
    t = DATA["board"].totals  # type: ignore[attr-defined]
    change, pct = _change()
    strip = [
        ("Wartość portfela", format_pln(t.value), "k-hero"),
        ("Zmiana od wczoraj", f"{format_pln(change, signed=True)} ({format_percent(pct, signed=True)})", None),
        ("Niezrealizowany zysk", format_pln(t.unrealized, signed=True), None),
        ("XIRR", "—" if t.xirr is None else format_percent(t.xirr * 100), "k-accent"),
    ]
    with ui.row().classes("k-card w-full p-0 gap-0 no-wrap"):
        for i, (label, value, cls) in enumerate(strip):
            style = "" if i == 0 else "border-left:1px solid var(--border)"
            with ui.column().classes("grow p-5 gap-0").style(style):
                ui.label(label).classes("text-xs uppercase tracking-wider k-muted")
                ui.label(value).classes(f"{'text-4xl' if i == 0 else 'text-2xl'} font-bold {cls or _sign_class(value)}")
    with ui.row().classes("k-card w-full px-6 py-3"):
        _goal(compact=True)
    tiles = {key: (title, value, note) for key, title, _, value, note in _tiles()}
    groups = [
        ("Kapitał", ["net-deposits", "open-positions", "cash"]),
        ("Wyniki", ["unrealized", "realized", "dividends"]),
        ("Koszty", ["costs"]),
    ]
    with ui.row().classes("w-full gap-4 no-wrap items-stretch"):
        with ui.column().classes("k-card p-5 grow gap-2"):
            ui.label("Wartość portfela w czasie").classes("font-semibold")
            _value_chart(theme, "h-80")
        with ui.column().classes("k-card p-5 w-96 shrink-0 gap-4"):
            for group, keys in groups:
                ui.label(group).classes("text-xs uppercase tracking-wider k-accent font-semibold")
                for key in keys:
                    title, value, note = tiles[key]
                    with ui.row().classes("w-full items-baseline no-wrap").style(
                        "border-bottom:1px dashed var(--border)"):  # fmt: skip
                        ui.label(title).classes("text-sm k-muted grow")
                        ui.label(value).classes("font-semibold")
                    if note:
                        ui.label(note).classes("text-xs k-muted self-end -mt-2")
    with ui.column().classes("k-card p-5 w-full gap-0"):
        ui.label("Konta").classes("font-semibold mb-2")
        total = t.value
        cols = "grid-template-columns: 2fr 1fr 1fr 2fr 8rem"
        with ui.element("div").classes("grid w-full text-xs uppercase tracking-wider k-muted pb-2").style(cols):
            for h in ("Konto", "Wartość", "30 dni", "Udział w portfelu", "90 dni"):
                ui.label(h)
        for name, value, pct, series in _accounts():
            share = value / total * 100 if total else Decimal(0)
            text = format_percent(pct, signed=True)
            with ui.element("div").classes("grid w-full items-center py-2").style(
                f"{cols}; border-top:1px solid var(--border)"):  # fmt: skip
                ui.label(name).classes("font-medium")
                ui.label(format_pln(value))
                ui.label(text).classes(_sign_class(text))
                with ui.row().classes("items-center gap-2 no-wrap pr-6"):
                    ui.linear_progress(value=float(share / 100), show_value=False, size="8px").props(
                        "rounded").classes("k-accent grow")  # fmt: skip
                    ui.label(format_percent(share, 1)).classes("text-sm k-muted w-16 text-right")
                _sparkline(series, theme)


# ---------------------------------------------------------------------------------------------------------- wariant C


def variant_c(theme: str) -> None:
    """C: raport: wąska kolumna z liczbami jak wyciąg (od wpłat do wyniku), po prawej wykres i konta."""
    _title_row()
    t = DATA["board"].totals  # type: ignore[attr-defined]
    with ui.row().classes("w-full gap-6 no-wrap items-start"):
        with ui.column().classes("k-card p-6 w-96 shrink-0 gap-3"):
            _hero_value("text-4xl")
            ui.separator().classes("opacity-30")
            ui.label("Skąd ta wartość").classes("text-xs uppercase tracking-wider k-accent font-semibold")
            net = t.net_deposits or Decimal(0)
            ladder = [
                ("Wpłaty netto", format_pln(net), ""),
                ("+ wynik łącznie", format_pln(t.value - net, signed=True), ""),
                ("= wartość portfela", format_pln(t.value), "strong"),
                ("w tym niezrealizowany zysk", format_pln(t.unrealized, signed=True), "sub"),
                ("w tym zrealizowany zysk", format_pln(t.realized, signed=True), "sub"),
                ("w tym dywidendy i odsetki", format_pln(t.dividends, signed=True), "sub"),
                ("zapłacone prowizje i koszty", format_pln(t.costs), "sub"),
            ]
            for label, value, kind in ladder:
                with ui.row().classes(f"w-full no-wrap items-baseline {'pl-4' if kind == 'sub' else ''}").style(
                    "border-top:2px solid var(--accent)" if kind == "strong" else ""):  # fmt: skip
                    ui.label(label).classes(f"grow {'font-semibold' if kind == 'strong' else 'k-muted text-sm'}")
                    style = {"strong": "text-lg font-bold k-hero", "sub": "text-sm"}.get(kind, "font-medium")
                    ui.label(value).classes(style)
            ui.separator().classes("opacity-30")
            ui.label("Na co to się składa").classes("text-xs uppercase tracking-wider k-accent font-semibold")
            for label, value in (("Otwarte pozycje", t.open_positions), ("Gotówka", t.cash)):
                share = value / t.value * 100 if t.value else Decimal(0)
                with ui.column().classes("w-full gap-1"):
                    with ui.row().classes("w-full no-wrap"):
                        ui.label(label).classes("grow text-sm")
                        ui.label(f"{format_pln(value)} · {format_percent(share, 1)}").classes("text-sm")
                    ui.linear_progress(value=float(share / 100), show_value=False, size="6px").props(
                        "rounded").classes("k-accent")  # fmt: skip
            with ui.row().classes("w-full no-wrap items-center k-btn p-3 mt-2"):
                ui.label("XIRR").classes("grow font-semibold")
                ui.label("—" if t.xirr is None else format_percent(t.xirr * 100)).classes("text-2xl font-bold k-accent")
            ui.separator().classes("opacity-30")
            _goal(compact=True)
        with ui.column().classes("grow gap-6"):
            with ui.column().classes("k-card p-5 w-full gap-2"):
                _value_chart(theme, "h-96")
            with ui.element("div").classes("grid grid-cols-2 gap-4 w-full"):
                for i, (name, value, pct, series) in enumerate(_accounts()):
                    text = format_percent(pct, signed=True)
                    with ui.row().classes("k-card p-4 items-center no-wrap gap-4"):
                        ui.element("div").classes("w-1 self-stretch rounded").style(
                            f"background:{ACCOUNT_COLOURS[i]}")  # fmt: skip
                        with ui.column().classes("gap-0 grow"):
                            ui.label(name).classes("text-sm k-muted")
                            ui.label(format_pln(value)).classes("text-xl font-semibold")
                            ui.label(f"{text} w 30 dni").classes(f"text-xs {_sign_class(text)}")
                        _sparkline(series, theme)


# ------------------------------------------------------------------------------------------------------- przełącznik


def _switcher(variant: str, theme: str) -> None:
    keys = list(VARIANTS)

    def go(step: int) -> None:
        ui.navigate.to(f"/?variant={keys[(keys.index(variant) + step) % len(keys)]}&theme={theme}")

    with ui.page_sticky(position="bottom", y_offset=20):
        with ui.row().classes("k-proto-bar items-center gap-2 px-3 py-1"):
            ui.label("PROTOTYP").classes("text-xs font-bold text-pink-300 mr-2")
            ui.button(icon="chevron_left", on_click=lambda: go(-1)).props("flat round dense color=white")
            ui.label(f"{variant} ({VARIANTS[variant]})").classes("text-sm w-56 text-center")
            ui.button(icon="chevron_right", on_click=lambda: go(1)).props("flat round dense color=white")
            ui.separator().props("vertical").classes("mx-2 bg-gray-600")
            for key, name in THEMES.items():
                ui.button(name, on_click=lambda k=key: ui.navigate.to(f"/?variant={variant}&theme={k}")).props(
                    f"flat dense no-caps color={'amber' if key == theme else 'grey-5'}")  # fmt: skip
    ui.keyboard(on_key=lambda e: go(-1 if e.key.arrow_left else 1)
                if e.action.keydown and (e.key.arrow_left or e.key.arrow_right) else None)  # fmt: skip


@ui.page("/")
def index(variant: str = "A", theme: str = "jasny") -> None:
    variant = variant if variant in VARIANTS else "A"
    theme = theme if theme in THEMES else "jasny"
    ui.add_css(CSS)
    ui.query("body").classes(f"theme-{theme}")
    ui.colors(primary="#d4af37" if theme == "golden" else "#2563eb")
    _sidebar()
    _header(variant, theme)
    with ui.column().classes("w-full max-w-screen-2xl px-6 pb-24 gap-5"):
        {"A": variant_a, "B": variant_b, "C": variant_c}[variant](theme)
    _switcher(variant, theme)


ui.run(port=8090, show=False, reload=False, language="pl", title="KAPITA – prototyp Dashboardu")
