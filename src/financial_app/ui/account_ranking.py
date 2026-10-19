"""The Total Dashboard's Accounts treemap and Account ranking (issue #89, spec section 5).

The treemap sizes each Account by its value and colours it by its P&L against its Net Deposits; clicking a tile
switches the View Scope to that Account. The ranking lists each Account's XIRR, TWR, P&L, Net Deposits and costs,
sorted by a clicked column (again: the other way), the best and worst of each column marked.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from nicegui import ui
from nicegui.events import EChartPointClickEventArguments

from financial_app.domain.account_ranking import (
    RankingColumn,
    RankingRow,
    TreemapTile,
    best_and_worst,
    sort_ranking,
    treemap_tiles,
)
from financial_app.domain.formatting import format_percent, format_pln
from financial_app.domain.themes import Theme
from financial_app.ui.charts import PLN_FORMATTER, zoom_button
from financial_app.ui.info import card_title
from financial_app.ui.theme import TILE_GAIN, TILE_LOSS, TILE_PALE, TILE_UNKNOWN, current_theme, echart, readable_label

DASH = "—"
# The tile colours run from pale at no P&L to full at this share of the Net Deposits
_FULL_COLOUR_AT = Decimal("0.3")
TREEMAP_INFO = (
    "Każde konto to prostokąt: im większy, tym większa wartość konta. Kolor to zysk lub strata względem wpłat "
    "netto: zielony to zysk, czerwony strata, a im ciemniejszy, tym większy (pełny kolor od 30 % wpłat); szary "
    "oznacza konto bez wyliczonego wyniku.\n\nKliknięcie konta przełącza widok na to konto."
)
RANKING_INFO = (
    "Konta obok siebie: XIRR (roczna stopa zwrotu z uwzględnieniem terminów wpłat), TWR (stopa zwrotu bez wpływu "
    "wpłat i wypłat, dobra do porównania kont), zysk lub strata, wpłaty netto i koszty.\n\n"
    "Kliknij nagłówek, by posortować; ponowne kliknięcie odwraca kolejność. Zielona pogrubiona wartość to najlepsza "
    "w kolumnie, czerwona najgorsza."
)


def accounts_treemap(rows: Sequence[RankingRow], switch: Callable[[int], None]) -> None:
    """The treemap of the Accounts holding something, largest first; a click on a tile calls ``switch`` with its
    Account id."""
    tiles = treemap_tiles(sorted(rows, key=lambda row: row.value, reverse=True))
    theme = current_theme()
    ids = {tile.account.name: tile.account.id for tile in tiles}
    tooltip = (
        f"p => {{ const pln = {PLN_FORMATTER}; return p.name + '<br>' + pln(p.value)"
        " + '<br>Zysk / strata: ' + pln(p.data.profit); }"
    )
    options: dict[str, Any] = {
        "tooltip": {":formatter": tooltip},
        "series": [
            {
                "type": "treemap",
                "name": "Konta",
                "roam": False,
                "nodeClick": False,
                "breadcrumb": {"show": False},
                "width": "100%",
                "height": "100%",
                "data": [_tile(tile, theme) for tile in tiles],
            }
        ],
    }

    def clicked(event: EChartPointClickEventArguments) -> None:
        if event.name in ids:
            switch(ids[event.name])

    with ui.card().classes("relative w-full gap-1"):
        card_title("Konta", TREEMAP_INFO, "accounts-treemap")
        echart(options, on_point_click=clicked).classes("w-full h-72").mark("chart-accounts-treemap")
        zoom_button("Konta", "accounts-treemap", options, clicked)


@dataclass(frozen=True)
class TileColours:
    """A treemap tile's colour and its label's, black or white, whichever reads better on it."""

    background: str
    label: str


def tile_colours(share: Decimal | None, theme: Theme) -> TileColours:
    """Green for a gain, red for a loss, the deeper the larger against the Net Deposits, from the ``theme``'s pale tile
    at no P&L; grey without a result."""
    if share is None:
        background = TILE_UNKNOWN[theme]
    else:
        strength = min(abs(share) / _FULL_COLOUR_AT, Decimal(1))
        full = TILE_GAIN if share >= 0 else TILE_LOSS
        channels = (
            round(pale + (deep - pale) * float(strength)) for pale, deep in zip(TILE_PALE[theme], full, strict=True)
        )
        background = "#" + "".join(f"{channel:02x}" for channel in channels)
    return TileColours(background, readable_label(background))


def _tile(tile: TreemapTile, theme: Theme) -> dict[str, Any]:
    """A treemap tile's data: its name, value, P&L for the tooltip, and its colours in ``theme``."""
    colours = tile_colours(tile.profit_share, theme)
    return {
        "name": tile.account.name,
        "value": round(float(tile.value), 2),
        "profit": None if tile.profit is None else round(float(tile.profit), 2),
        "itemStyle": {"color": colours.background},
        "label": {"color": colours.label},
    }


RANKING_COLUMNS = "grid-template-columns: minmax(8rem, 2fr) repeat(5, minmax(7rem, 1fr))"


@dataclass
class AccountRanking:
    """The ranking table; it keeps the chosen column and direction across the Dashboard's redraws."""

    column: RankingColumn = RankingColumn.PROFIT
    descending: bool = True

    def build(self, rows: Sequence[RankingRow]) -> None:
        """The table of ``rows``, sorted by the chosen column; a click on a column's header sorts by it, highest
        first, or the other way when it is already the column."""

        @ui.refreshable
        def table() -> None:
            self._table(rows, sort_by)

        def sort_by(column: RankingColumn) -> None:
            self.descending = not self.descending if column is self.column else True
            self.column = column
            table.refresh()

        with ui.card().classes("w-full overflow-x-auto").mark("account-ranking"):
            card_title("Ranking kont", RANKING_INFO, "account-ranking")
            table()

    def _table(self, rows: Sequence[RankingRow], sort_by: Callable[[RankingColumn], None]) -> None:
        with ui.element("div").classes("grid w-full gap-x-4 border-b py-1 text-sm font-medium").style(RANKING_COLUMNS):
            ui.label("Konto")
            for column in RankingColumn:
                arrow = ("↓" if self.descending else "↑") if column is self.column else ""
                button = ui.button(f"{column.label} {arrow}".strip(), on_click=lambda c=column: sort_by(c))
                button.props("flat dense no-caps").classes("justify-self-end").mark(f"ranking-sort-{column}")
        extremes = {column: best_and_worst(rows, column) for column in RankingColumn}
        for row in sort_ranking(rows, self.column, self.descending):
            line = ui.element("div").classes("grid w-full gap-x-4 border-b py-1 text-sm").style(RANKING_COLUMNS)
            with line.mark("ranking-row"):
                ui.label(row.account.name).classes("font-medium")
                for column in RankingColumn:
                    cell = ui.label(_text(column, row.figure(column))).classes("text-right")
                    best, worst = extremes[column]
                    if row.account.id == best:
                        cell.classes("text-positive font-bold").mark("ranking-best")
                    elif row.account.id == worst:
                        cell.classes("text-negative font-bold").mark("ranking-worst")


def _text(column: RankingColumn, figure: Decimal | None) -> str:
    if figure is None:
        return DASH
    if column in (RankingColumn.XIRR, RankingColumn.TWR):
        return format_percent(figure * 100)
    return format_pln(figure, signed=column is RankingColumn.PROFIT)
