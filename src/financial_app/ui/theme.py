"""The window's Theme (issue #174): Jasny, or Golden on Quasar's dark mode with gold accents and mountains behind.

Colours are CSS variables of one set per Theme on ``body`` (``theme-jasny``, ``theme-golden``), so a page styles with
the ``k-`` classes below and never names a colour; Quasar's ``primary`` and the custom ``ink`` (header text) and
``attention`` (pending Drafts) follow the Theme too. ECharts draws on canvas, so its charts take ``chart_theme()``
through ``echart``. Choosing a Theme reloads the window, which then builds every tab and chart in it.
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from nicegui import context, ui
from sqlalchemy import Engine

from financial_app.domain.strategy import BandStatus
from financial_app.domain.themes import Theme, parse_theme
from financial_app.persistence.settings import UI_THEME, load_setting, save_setting

# Where a page under construction finds its window's Theme (the client's storage lasts as long as its connection)
_CLIENT_KEY = "theme"

_QUASAR = {
    Theme.LIGHT: {
        "primary": "#2563eb",
        "ink": "#0f172a",
        "side": "#cbd5e1",
        "side_active": "#ffffff",
        "attention": "#b45309",
        "negative": "#dc2626",
    },
    Theme.GOLDEN: {
        "primary": "#d4af37",
        "ink": "#f2f2f2",
        "side": "#d4d4d4",
        "side_active": "#d4af37",
        "attention": "#fbbf24",
        "negative": "#ef4444",
        "dark": "#141414",
        "dark_page": "#0b0b0c",
    },
}

# Gold peaks fading into the dark, behind the header and at the foot of the menu
_MOUNTAINS = (
    "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 800 300' "
    "preserveAspectRatio='none'><defs><linearGradient id='g' x1='0' y1='0' x2='0' y2='1'>"
    "<stop offset='0' stop-color='%23d4af37' stop-opacity='0.3'/><stop offset='1' stop-color='%23000' "
    "stop-opacity='0'/></linearGradient></defs><path fill='url(%23g)' d='M0 300 L0 210 L90 150 L150 185 L260 60 "
    "L330 130 L390 95 L470 170 L560 80 L640 140 L720 110 L800 160 L800 300 Z'/></svg>\")"
)

# The text of each Theme (its --k-text) and, behind it, the Investment Strategy's band rows: pale in Jasny, deep in
# Golden, so the text stays readable in both
# Each Theme's page, card and hovered row, and the text tones on them: the CSS's --k-<name>, and the k-muted, k-gain,
# k-loss, k-warning and k-hover classes a page names instead of a colour
THEME_COLOURS = {
    Theme.LIGHT: {
        "page": "#f4f6fa",
        "card": "#ffffff",
        "hover": "#f1f5f9",
        "text": "#0f172a",
        "muted": "#475569",
        "gain": "#166534",
        "loss": "#b91c1c",
        "warning": "#9a3412",
        "field": "#e3f2fd",
    },
    Theme.GOLDEN: {
        "page": "#0b0b0c",
        "card": "#141414",
        "hover": "#262626",
        "text": "#f2f2f2",
        "muted": "#a3a3a3",
        "gain": "#22c55e",
        "loss": "#f87171",
        "warning": "#fb923c",
        "field": "#2a2416",
    },
}
TEXT_COLOURS = {theme: colours["text"] for theme, colours in THEME_COLOURS.items()}
_THEME_CSS = "".join(
    f"body.theme-{theme.value} {{ " + " ".join(f"--k-{name}:{colour};" for name, colour in colours.items()) + " }\n"
    for theme, colours in THEME_COLOURS.items()
)
BAND_COLOURS = {
    # Pale tints, so that a class row is marked without the whole table shouting
    Theme.LIGHT: {BandStatus.GREEN: "#edf7ee", BandStatus.YELLOW: "#fff4d1", BandStatus.RED: "#fde7e7"},
    Theme.GOLDEN: {BandStatus.GREEN: "#163a24", BandStatus.YELLOW: "#3d3210", BandStatus.RED: "#45191b"},
}
# The Accounts treemap's tiles (ui/account_ranking.py): from the tile without P&L, pale in Jasny and the dark of a
# card in Golden, towards the gain's green or the loss's red; a soft neutral without a result (while History is
# computed), close to the page rather than a grey that reads as broken
TILE_PALE = {Theme.LIGHT: (232, 245, 233), Theme.GOLDEN: (38, 38, 38)}
TILE_GAIN, TILE_LOSS = (46, 125, 50), (198, 40, 40)
TILE_UNKNOWN = {Theme.LIGHT: "#dfe5ee", Theme.GOLDEN: "#333333"}
# The relative luminance at which black and white text contrast alike: (L + 0.05) / 0.05 = 1.05 / (L + 0.05)
_EVEN_CONTRAST = (1.05 * 0.05) ** 0.5 - 0.05


def gain_or_loss(amount: Decimal | None) -> str:
    """The class colouring a signed amount: ``k-gain`` above zero, ``k-loss`` below, none at zero or without one; every
    tab colours a result, a difference or a cash change alike."""
    if amount is None or amount == 0:
        return ""
    return "k-gain" if amount > 0 else "k-loss"


def readable_label(background: str) -> str:
    """Black or white, whichever contrasts more with the ``#rrggbb`` ``background``; by WCAG either reaches 4.5:1 on
    any colour between them."""
    return "#000000" if luminance(background) > _EVEN_CONTRAST else "#ffffff"


def luminance(colour: str) -> float:
    """WCAG relative luminance of a ``#rrggbb`` colour."""
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


_BAND_CSS = "".join(
    f"body.theme-{theme.value} .k-band-{status.value} {{ background:{colour}; }}\n"
    for theme, colours in BAND_COLOURS.items()
    for status, colour in colours.items()
)

CSS = (
    """
body.theme-jasny { --k-side:#0f1b33; --k-side-text:#cbd5e1; --k-side-active:#1e2b48;
  --k-border:#e5e9f0; --k-accent:#2563eb;
  --k-hero:#0f172a; --k-chip:#eef2f7; --k-highlight:#eef2ff; }
body.theme-golden { --k-side:#0e0e0f; --k-side-text:#d4d4d4; --k-side-active:#2a2416;
  --k-border:rgba(212,175,55,.22); --k-accent:#d4af37;
  --k-hero:#e8c766; --k-chip:#262626; --k-highlight:#2a2416; }
body { background:var(--k-page); color:var(--k-text); }
body.theme-golden { background:var(--k-page) MOUNTAINS no-repeat right top / 70% 260px; }
.k-header { background:var(--k-page); color:var(--k-text); border-bottom:1px solid var(--k-border); }
body.theme-golden .k-header { background:var(--k-page) MOUNTAINS no-repeat right top / 70% 260px fixed; }
.k-avatar { display:inline-flex; align-items:center; justify-content:center; width:36px; height:36px;
  border-radius:50%; color:#fff; font-weight:700; font-size:0.85rem; }
.k-side { background:var(--k-side); color:var(--k-side-text); }
body.theme-golden .k-side { background:var(--k-side) MOUNTAINS no-repeat bottom / 100% 320px;
  border-right:1px solid var(--k-border); }
.k-menu-item { color:var(--k-side-text) !important; border-radius:10px; }
.k-menu-item.k-active { background:var(--k-side-active); color:#fff !important;
  box-shadow:inset 3px 0 0 var(--k-accent); }
body.theme-golden .k-menu-item.k-active { color:var(--k-accent) !important; }
.q-card { border:1px solid var(--k-border); border-radius:14px; box-shadow:0 1px 3px rgba(15,23,42,.06); }
body.theme-golden .q-card { background:linear-gradient(180deg,#171717,#101010); }
/* Buttons and tabs as written ("Eksportuj XLSX"), as most already are with no-caps, never Quasar's capitals */
.q-btn, .q-tab { text-transform:none; }
/* A table's row lines in the Theme's soft border, not the text colour Tailwind's border-t/-b fall back to */
.border-t, .border-b { border-color:var(--k-border); }
/* A link in the Theme's accent (gold in Golden), not the browser's blue */
a.nicegui-link { color:var(--q-primary); }
/* Quasar paints tab panels white (dark grey in dark mode): beside a card narrower than the page it showed as a band */
.q-tab-panels { background:transparent; }
.k-faq { background:#fff; border-radius:4px; }
body.theme-golden .k-faq { background:#171717; }
.k-undo, .k-covering { position:fixed; bottom:24px; left:50%; transform:translateX(-50%); z-index:6000;
  background:var(--k-text); color:var(--k-page); border-radius:10px; padding:6px 8px 6px 16px;
  box-shadow:0 4px 14px rgba(0,0,0,.3); }
.k-covering { bottom:76px; }
.k-undo .q-btn, .k-covering .q-btn { color:inherit; font-weight:700; text-decoration:underline; }
.k-muted { color:var(--k-muted); }
.k-gain { color:var(--k-gain); }
.k-loss { color:var(--k-loss); }
.k-warning { color:var(--k-warning); }.k-hover:hover { background:var(--k-hover); }
.k-hover[class*="k-band-"]:hover { box-shadow:inset 0 0 0 100vmax rgba(128,128,128,.18); }
body .k-field.q-field--filled .q-field__control { background:var(--k-field); }
.k-hero { color:var(--k-hero); }
.k-accent { color:var(--k-accent); }
.k-highlight { background:var(--k-highlight); }
/* An Account's View Scope: the header's switcher and the breadcrumbs' last step outlined in the accent, and its row
   in the switcher's menu marked like the lit menu item */
body .k-scope-chosen { background:var(--k-highlight); color:var(--k-accent) !important; font-weight:700;
  box-shadow:inset 0 0 0 1.5px var(--k-accent); border-radius:999px; }
.k-scope-row.k-highlight { box-shadow:inset 3px 0 0 var(--k-accent); }
.k-scope-row.k-highlight .k-scope-name { color:var(--k-accent); font-weight:700; }
.k-icon { width:44px; height:44px; border-radius:999px; display:flex; align-items:center; justify-content:center; }
body.theme-golden .k-icon { background:rgba(212,175,55,.12) !important; color:var(--k-accent) !important; }
.q-linear-progress__track { background:var(--k-chip) !important; opacity:1 !important; }
.q-circular-progress__track { color:var(--k-chip) !important; opacity:1 !important; }
""".replace("MOUNTAINS", _MOUNTAINS)
    + _THEME_CSS
    + _BAND_CSS
)

_GOLDEN_AXIS = {
    "axisLine": {"lineStyle": {"color": "#525252"}},
    "axisLabel": {"color": "#a3a3a3"},
    "splitLine": {"lineStyle": {"color": ["#262626"]}},
}
# The light Theme keeps ECharts' own look; Golden turns it dark with gold first among the series colours
_CHART_THEMES: dict[Theme, dict[str, Any] | None] = {
    Theme.LIGHT: None,
    Theme.GOLDEN: {
        "backgroundColor": "transparent",
        "color": ["#d4af37", "#22c55e", "#60a5fa", "#f97316", "#a78bfa", "#ef4444", "#2dd4bf", "#f472b6"],
        "textStyle": {"color": "#d4d4d4"},
        "legend": {"textStyle": {"color": "#d4d4d4"}},
        "categoryAxis": _GOLDEN_AXIS,
        "valueAxis": _GOLDEN_AXIS,
        "timeAxis": _GOLDEN_AXIS,
        "tooltip": {"backgroundColor": "#1c1c1c", "borderColor": "#d4af37", "textStyle": {"color": "#f2f2f2"}},
    },
}
# The value line of the Dashboard's main chart and the gain and loss of the Accounts' small ones
LINE_COLOURS = {
    Theme.LIGHT: {"value": "#16a34a", "area": "rgba(22,163,74,.20)", "gain": "#16a34a", "loss": "#dc2626"},
    Theme.GOLDEN: {"value": "#d4af37", "area": "rgba(212,175,55,.28)", "gain": "#22c55e", "loss": "#ef4444"},
}
# The labels a chart draws itself (the waterfall's changes)
LABEL_COLOURS = {Theme.LIGHT: "#424242", Theme.GOLDEN: "#d4d4d4"}


class ThemeChoice:
    """A window's Theme, remembered in ``app_settings`` for every View Scope."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.theme = parse_theme(load_setting(engine, UI_THEME))
        self.listeners: list[Callable[[], None]] = []

    def on_change(self, listener: Callable[[], None]) -> None:
        self.listeners.append(listener)

    def choose(self, theme: Theme) -> None:
        """Remember ``theme``, then tell whatever follows it (the shell reloads the window)."""
        self.theme = theme
        save_setting(self.engine, UI_THEME, theme.value)
        for listener in self.listeners:
            listener()


def apply_theme(theme: Theme) -> None:
    """Style the page being built in ``theme``: its CSS, Quasar's colours and dark mode, and the charts' Theme."""
    context.client.storage[_CLIENT_KEY] = theme.value
    ui.add_css(CSS)
    ui.query("body").classes(f"theme-{theme.value}")
    ui.colors(**_QUASAR[theme])
    ui.dark_mode(theme is Theme.GOLDEN)


def current_theme() -> Theme:
    """The Theme of the window being built (Jasny outside one, e.g. in a test building a lone chart)."""
    try:
        return parse_theme(context.client.storage.get(_CLIENT_KEY))
    except RuntimeError:
        return Theme.LIGHT


def chart_theme() -> dict[str, Any] | None:
    return _CHART_THEMES[current_theme()]


def echart(options: dict[str, Any], **kwargs: Any) -> ui.echart:
    """``ui.echart`` in the window's Theme."""
    return ui.echart(options, theme=chart_theme(), **kwargs)


def theme_section(choice: ThemeChoice) -> None:
    """The Theme's toggle in Wygląd i widoczność, marked ``ui-theme``."""
    with ui.row().classes("items-center gap-4"):
        ui.label("Motyw").classes("font-medium")
        toggle = ui.toggle(
            {theme.value: theme.label for theme in Theme},
            value=choice.theme.value,
            on_change=lambda event: choice.choose(parse_theme(event.value)),
        )
        toggle.props("no-caps unelevated toggle-color=primary").mark("ui-theme")
