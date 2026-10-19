"""What the window shows (issue #155): the Dashboard elements and tabs the user can hide, and the View Profiles.

Hiding changes only the view; every calculation runs the same. The hidden elements are remembered as a JSON list of
their keys, one setting for every View Scope; nothing remembered shows everything (Pełny). The Dashboard, Portfolio,
Transakcje, Ustawienia and Pomoc tabs are always shown, so they have no key.
"""

import json
from dataclasses import dataclass
from enum import Enum


class Profile(Enum):
    """A View Profile: a preset of what is shown, or Własny for any other choice."""

    BASIC = "Podstawowy"
    FULL = "Pełny"
    CUSTOM = "Własny"


@dataclass(frozen=True)
class Element:
    """A Dashboard element or tab that can be hidden; ``key`` is its marker on the Dashboard (``tile-…``,
    ``chart-…``) or ``tab-`` and its tab's path."""

    key: str
    label: str
    group: str


TILES = "Kafelki"
SECTIONS = "Sekcje Dashboardu"
CHARTS = "Wykresy"
TABS = "Zakładki"

ELEMENTS = (
    Element("tile-net-deposits", "Wpłaty netto", TILES),
    Element("tile-value", "Wartość konta", TILES),
    Element("tile-open-positions", "Otwarte pozycje", TILES),
    Element("tile-cash", "Gotówka", TILES),
    Element("tile-unrealized", "Niezrealizowany zysk", TILES),
    Element("tile-realized", "Zrealizowany zysk", TILES),
    Element("tile-dividends", "Dywidendy i odsetki", TILES),
    Element("tile-costs", "Prowizje i koszty", TILES),
    Element("tile-xirr", "XIRR", TILES),
    Element("since-snapshot", "Zmiana od migawki", SECTIONS),
    Element("investment-goal", "Cel inwestycyjny / FIRE", SECTIONS),
    Element("sayings", "Cytat dnia (Dashboard i menu)", SECTIONS),
    Element("account-table", "Twoje konta i aktywa (karty i tabela)", SECTIONS),
    Element("contribution-limits", "Limity wpłat", SECTIONS),
    Element("account-ranking", "Ranking i treemap kont", SECTIONS),
    Element("currency-exposure", "Waluty w portfelu", SECTIONS),
    Element("strategy", "Strategia inwestycyjna", SECTIONS),
    Element("chart-waterfall", "Wynik według źródeł", CHARTS),
    Element("chart-dividends", "Dywidendy i odsetki w latach", CHARTS),
    Element("chart-currencies", "Waluty (wykres)", CHARTS),
    Element("chart-accounts", "Wartość kont", CHARTS),
    Element("chart-allocation", "Alokacja", CHARTS),
    Element("chart-class-shares", "Udział aktywów w czasie", CHARTS),
    Element("chart-value", "Wartość konta vs wpłaty netto", CHARTS),
    Element("chart-profit", "Zysk / strata", CHARTS),
    Element("chart-xirr", "XIRR (wykres)", CHARTS),
    Element("chart-drawdown", "Drawdown", CHARTS),
    Element("tab-wyniki", "Wyniki", TABS),
    Element("tab-strategie", "Strategie inwestycyjne", TABS),
    Element("tab-obligacje", "Dochód stały", TABS),
    Element("tab-multi-asset", "Multi-asset", TABS),
    Element("tab-benchmarki", "Benchmarki", TABS),
    Element("tab-sprzedaz", "Podsumowanie sprzedaży", TABS),
    Element("tab-dochod-pasywny", "Dochód pasywny", TABS),
)
KEYS = frozenset(element.key for element in ELEMENTS)

# What Podstawowy keeps for a beginner with one Account and a few ETFs; the sayings (#178) too, so a Podstawowy saved
# before them still reads as Podstawowy
_BASIC_SHOWN = frozenset(
    {
        "tile-value",
        "tile-net-deposits",
        "tile-unrealized",
        "account-table",
        "chart-value",
        "chart-allocation",
        "sayings",
    }
)
_PRESETS = {Profile.FULL: frozenset[str](), Profile.BASIC: KEYS - _BASIC_SHOWN}


def tab_key(path: str) -> str:
    """The key of the tab at ``path``; the always shown tabs' keys name no element."""
    return "tab-" + path.strip("/")


def preset_hidden(profile: Profile) -> frozenset[str]:
    """The elements a preset hides; Własny has none of its own, so it hides nothing."""
    return _PRESETS.get(profile, frozenset())


def profile_of(hidden: frozenset[str]) -> Profile:
    """The preset hiding exactly ``hidden``, else Własny."""
    return next((profile for profile, preset in _PRESETS.items() if preset == hidden), Profile.CUSTOM)


def visibility_setting(hidden: frozenset[str]) -> str:
    """The text the hidden elements are remembered as: their keys, sorted, as a JSON list."""
    return json.dumps(sorted(hidden))


def parse_visibility(text: str | None) -> frozenset[str]:
    """The remembered hidden elements; keys of no element are dropped, unreadable text hides nothing."""
    try:
        keys = json.loads(text) if text is not None else []
    except json.JSONDecodeError:
        return frozenset()
    if not isinstance(keys, list):
        return frozenset()
    return frozenset(key for key in keys if isinstance(key, str)) & KEYS
