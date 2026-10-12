"""Multi-asset Splits (issue #75, spec 3.2 and 5): the split editor shared by the Instrument dialog and the split
dialog, and the Multi-asset tab listing the Multi-asset Instruments held with their value in each Asset Class."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_percent, format_pln, format_quantity, parse_number
from financial_app.domain.instruments import MULTI_ASSET_CLASS, AssetClass, Instrument, InstrumentError
from financial_app.domain.lots import open_positions
from financial_app.domain.multi_asset import MultiAssetHolding, multi_asset_holdings
from financial_app.persistence.instruments import list_asset_classes, list_instruments, set_multi_asset_split
from financial_app.persistence.transactions import list_transactions
from financial_app.sources.current_prices import TodaysRates, current_prices
from financial_app.sources.nbp import NbpRates
from financial_app.sources.prices import last_refresh
from financial_app.ui.dialogs import movable_dialog
from financial_app.ui.view_scope import ViewScope


def is_multi_asset_class(name: str | None) -> bool:
    """Whether an Asset Class named ``name`` holds Instruments that a Multi-asset Split spreads across others."""
    return name is not None and name.casefold() == MULTI_ASSET_CLASS.casefold()


def split_editor(asset_classes: Sequence[AssetClass], split: Mapping[int, Decimal]) -> Callable[[], dict[int, Decimal]]:
    """A percent field per Asset Class (Multi-asset itself aside) filled from ``split``, with their running sum.

    Returns what reads the typed split (empty fields left out), raising ``InstrumentError`` for a field that is not a
    number; whether it sums to 100% is checked when it is saved.
    """
    fields: dict[int, ui.input] = {}
    with ui.column().classes("w-full gap-1").mark("multi-asset-split"):
        ui.label("Podział Multi-asset").classes("font-medium")
        ui.label("Jaki procent wartości instrumentu przypada na każdą klasę; razem 100%.").classes(
            "text-sm text-gray-500"
        )
        with ui.grid(columns=2).classes("w-full gap-x-4 gap-y-0"):
            for asset_class in asset_classes:
                if is_multi_asset_class(asset_class.name):
                    continue
                share = split.get(asset_class.id)
                field = ui.input(asset_class.name, value="" if share is None else format_quantity(share))
                field.props('dense suffix="%"').mark(f"split-share-{asset_class.id}")
                fields[asset_class.id] = field
        total = ui.label().classes("text-sm").mark("split-total")

    def typed() -> dict[int, Decimal]:
        shares: dict[int, Decimal] = {}
        for class_id, field in fields.items():
            text = (field.value or "").strip()
            if not text:
                continue
            try:
                shares[class_id] = parse_number(text)
            except ValueError:
                raise InstrumentError(f"Udział „{field.props['label']}” musi być liczbą, a nie „{text}”.") from None
        return shares

    def show_total() -> None:
        try:
            summed = sum(typed().values(), Decimal(0))
        except InstrumentError:
            total.text = "Razem: —"
            return
        total.text = f"Razem: {format_quantity(summed)}%"
        total.classes(replace="text-sm" if summed in (0, 100) else "text-sm text-negative")

    for field in fields.values():
        field.on_value_change(show_total)
    show_total()
    return typed


def open_split_dialog(engine: Engine, instrument: Instrument, on_saved: Callable[[], None]) -> None:
    """Edit only ``instrument``'s Multi-asset Split; ``on_saved`` runs after a save. Closing it without saving leaves
    the Instrument whole in its own class."""
    dialog = movable_dialog()
    dialog.on("hide", dialog.delete)
    with dialog, ui.card().classes("w-[480px]").mark("split-dialog"):
        ui.label(f"Podział Multi-asset: {instrument.name}").classes("text-lg font-bold")
        if not instrument.multi_asset_split:
            ui.label("Bez podziału instrument liczy się w całości do klasy Multi-asset.").classes(
                "text-sm text-gray-500"
            )
        typed = split_editor(list_asset_classes(engine), instrument.multi_asset_split)
        error = ui.label().classes("text-negative").mark("split-error")

        def save() -> None:
            try:
                set_multi_asset_split(engine, instrument.id, typed())
            except InstrumentError as exc:
                error.text = str(exc)
                return
            dialog.close()
            on_saved()

        with ui.row().classes("w-full justify-end"):
            ui.button("Anuluj", on_click=dialog.close).props("flat")
            ui.button("Zapisz", on_click=save).mark("save-split")
    dialog.open()


@dataclass
class MultiAssetPage:
    """The Multi-asset tab of the View Scope: each Multi-asset Instrument held, its value today and its split, the
    value it puts in each Asset Class and their sums; clicking one edits its split. ``on_split_saved`` lets History
    count the new split."""

    engine: Engine
    rates: NbpRates
    scope: ViewScope
    on_split_saved: Callable[[], None]

    def refresh(self) -> None:
        """Redraw the tab if it is on screen (e.g. after a save, a price refresh or a scope change)."""
        self.content.refresh()

    def build(self) -> None:
        ui.label("Multi-asset").classes("text-2xl font-bold")
        with ui.column().classes("w-full max-w-4xl").mark("multi-asset"):
            self.content()

    @ui.refreshable_method
    def content(self) -> None:
        # list_transactions is newest first; the FIFO engine wants entry order
        positions = open_positions(list(reversed(list_transactions(self.engine))))
        instruments = {i.id: i for i in list_instruments(self.engine)}
        held = [instruments[i] for i in {p.instrument_id for p in positions}]
        rates = TodaysRates(self.rates)
        prices = {
            i: price.pln for i, price in current_prices(self.engine, held, rates, last_refresh(self.engine)).items()
        }
        holdings = multi_asset_holdings(positions, instruments, prices, self.scope.account_id)
        if not holdings:
            ui.label(
                "Brak instrumentów Multi-asset w portfelu. Instrument klasy Multi-asset dostaje podział na klasy "
                "w swoim oknie w Ustawienia > Instrumenty."
            ).classes("text-gray-500").mark("multi-asset-empty")
            return
        for holding in holdings:
            self._holding_row(holding)
        _class_sums(holdings)

    def _holding_row(self, holding: MultiAssetHolding) -> None:
        instrument = holding.instrument

        def saved() -> None:
            self.refresh()
            self.on_split_saved()

        item = ui.item(on_click=lambda: open_split_dialog(self.engine, instrument, saved))
        item.classes("w-full border-b").mark(f"multi-asset-row multi-asset-row-{instrument.id}")
        with item, ui.item_section():
            with ui.row().classes("w-full items-center"):
                ui.label(instrument.name).classes("font-medium grow")
                value = format_pln(holding.value)
                ui.label(value if holding.priced else f"{value} (po koszcie)")
            if instrument.multi_asset_split:
                ui.label(_split_text(holding)).classes("text-sm text-gray-500")
            else:
                ui.label("Brak podziału: liczy się w całości do klasy Multi-asset. Kliknij, aby go dodać.").classes(
                    "text-sm text-warning"
                ).mark("multi-asset-no-split")


def _split_text(holding: MultiAssetHolding) -> str:
    """Each class of the split with its percent and PLN value, e.g. "Akcje zagraniczne 80% · 480,00 zł"."""
    shares = holding.instrument.multi_asset_split.values()
    return " · ".join(
        f"{name} {format_quantity(share)}%: {format_pln(value)}"
        for (name, value), share in zip(holding.parts, shares, strict=True)
    )


def _class_sums(holdings: Sequence[MultiAssetHolding]) -> None:
    """What the Multi-asset Instruments add to each Asset Class, largest first, with its share of their value."""
    sums: dict[str, Decimal] = {}
    for holding in holdings:
        for name, value in holding.parts:
            sums[name] = sums.get(name, Decimal(0)) + value
    total = sum(sums.values(), Decimal(0))
    ui.label("Razem w klasach aktywów").classes("text-lg font-bold mt-4")
    for name, value in sorted(sums.items(), key=lambda item: item[1], reverse=True):
        with ui.row().classes("w-full items-center border-b py-1").mark("multi-asset-class"):
            ui.label(name).classes("grow")
            ui.label(format_pln(value))
            ui.label(format_percent(value / total * 100 if total else Decimal(0))).classes("w-20 text-right")
