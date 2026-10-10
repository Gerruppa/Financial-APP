"""Ustawienia > Klasy aktywów and Instrumenty: the editable Asset Classes and the Instrument catalog (spec 3.2)."""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_exact, parse_number
from financial_app.domain.instruments import AssetClass, Instrument, InstrumentDraft, InstrumentError
from financial_app.domain.prices import YAHOO
from financial_app.persistence.instruments import (
    add_asset_class,
    add_instrument,
    delete_asset_class,
    delete_instrument,
    list_asset_classes,
    list_instruments,
    rename_asset_class,
    update_instrument,
)
from financial_app.ui.dialogs import movable_dialog


@dataclass
class AssetClassesSection:
    """The Klasy aktywów card; ``on_renamed`` lets other sections redraw the new name."""

    engine: Engine
    on_renamed: Callable[[], None]

    def build(self) -> None:
        with ui.card().classes("w-full max-w-4xl"):
            with ui.row().classes("w-full items-center"):
                ui.label("Klasy aktywów").classes("text-xl font-bold")
                ui.space()
                ui.button("Dodaj klasę", icon="add", on_click=lambda: self.open_dialog(None)).props("no-caps")
            # The marker sits outside the refreshable list so it survives a refresh
            with ui.column().classes("w-full gap-1").mark("asset-classes"):
                self.class_list()

    @ui.refreshable_method
    def class_list(self) -> None:
        for asset_class in list_asset_classes(self.engine):
            with ui.row().classes("w-full items-center no-wrap border-b py-1"):
                ui.label(asset_class.name).classes("grow")
                ui.button(icon="edit", on_click=lambda c=asset_class: self.open_dialog(c)).props(
                    f'flat round dense aria-label="Zmień nazwę {asset_class.name}"'
                ).mark(f"edit-asset-class-{asset_class.id}")

    def open_dialog(self, asset_class: AssetClass | None) -> None:
        """Open a form for a new Asset Class (``None``) or for renaming ``asset_class``."""
        dialog = movable_dialog()
        dialog.on("hide", dialog.delete)
        with dialog, ui.card().classes("w-[400px]"):
            ui.label("Nowa klasa aktywów" if asset_class is None else "Zmień nazwę klasy").classes("text-lg font-bold")
            name = ui.input("Nazwa", value=asset_class.name if asset_class else "").classes("w-full")
            name.mark("asset-class-name")
            error = ui.label().classes("text-negative").mark("asset-class-error")

            def save() -> None:
                try:
                    if asset_class is None:
                        add_asset_class(self.engine, name.value)
                    else:
                        rename_asset_class(self.engine, asset_class.id, name.value)
                except InstrumentError as exc:
                    error.text = str(exc)
                    return
                dialog.close()
                self.class_list.refresh()
                if asset_class is not None:
                    self.on_renamed()

            def delete() -> None:
                if asset_class is None:
                    return
                try:
                    delete_asset_class(self.engine, asset_class.id)
                except InstrumentError as exc:
                    error.text = str(exc)
                    return
                dialog.close()
                self.class_list.refresh()
                self.on_renamed()

            with ui.row().classes("w-full justify-between"):
                if asset_class is not None:
                    ui.button("Usuń", icon="delete", on_click=delete).props("flat color=negative no-caps").mark(
                        "delete-asset-class"
                    )
                else:
                    ui.space()
                with ui.row():
                    ui.button("Anuluj", on_click=dialog.close).props("flat")
                    ui.button("Zapisz", on_click=save)
        dialog.open()


@dataclass
class InstrumentsSection:
    """The Instrumenty card; ``refresh`` redraws the catalog after a save or an Asset Class rename."""

    engine: Engine

    def refresh(self) -> None:
        self.instrument_list.refresh()

    def build(self) -> None:
        with ui.card().classes("w-full max-w-4xl"):
            with ui.row().classes("w-full items-center"):
                ui.label("Instrumenty").classes("text-xl font-bold")
                ui.space()
                ui.button("Dodaj instrument", icon="add", on_click=lambda: self.open_dialog(None)).props("no-caps")
            with ui.column().classes("w-full gap-1").mark("instruments"):
                self.instrument_list()

    @ui.refreshable_method
    def instrument_list(self) -> None:
        instruments = list_instruments(self.engine)
        if not instruments:
            ui.label("Nie dodano jeszcze żadnego instrumentu.").classes("text-gray-500")
        for instrument in instruments:
            self._instrument_row(instrument)

    def _instrument_row(self, instrument: Instrument) -> None:
        with ui.row().classes("w-full items-center no-wrap border-b py-1"):
            with ui.column().classes("gap-0 grow"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(instrument.name).classes("font-medium")
                    ui.badge(instrument.asset_class_name).props("outline")
                details = [instrument.quote_currency, instrument.market]
                if instrument.manual_price is not None:
                    details.append(f"cena ręczna {format_exact(instrument.manual_price)} {instrument.quote_currency}")
                if YAHOO in instrument.source_symbols:
                    details.append(f"Yahoo {instrument.source_symbols[YAHOO]}")
                ui.label(" · ".join(d for d in details if d)).classes("text-sm text-gray-500")
            ui.button(icon="edit", on_click=lambda: self.open_dialog(instrument)).props(
                f'flat round aria-label="Edytuj {instrument.name}"'
            ).mark("edit-instrument")

    def open_dialog(self, instrument: Instrument | None) -> None:
        """Open a fresh form for a new Instrument (``None``) or for editing ``instrument``."""
        dialog = movable_dialog()
        dialog.on("hide", dialog.delete)
        class_options = {c.id: c.name for c in list_asset_classes(self.engine)}
        with dialog, ui.card().classes("w-[480px]").mark("instrument-dialog"):
            ui.label("Nowy instrument" if instrument is None else "Edytuj instrument").classes("text-lg font-bold")
            name = ui.input("Nazwa", value=instrument.name if instrument else "").classes("w-full")
            name.mark("instrument-name")
            asset_class = ui.select(
                class_options, label="Klasa aktywów", value=instrument.asset_class_id if instrument else None
            ).classes("w-full")
            asset_class.mark("instrument-class")
            currency = ui.input("Waluta notowania", value=instrument.quote_currency if instrument else "PLN")
            currency.classes("w-full").mark("instrument-currency")
            market = ui.input("Rynek", value=instrument.market if instrument else "")
            market.props('hint="Np. GPW, NYSE, XETRA; może zostać puste"').classes("w-full")
            market.mark("instrument-market")
            symbols = dict(instrument.source_symbols) if instrument else {}
            yahoo = ui.input("Symbol Yahoo", value=symbols.get(YAHOO, ""))
            yahoo.props('hint="Np. ISAC.L, AAPL, BTC-USD; zostaw puste, jeśli Yahoo nie notuje instrumentu"')
            yahoo.classes("w-full").mark("instrument-symbol-yahoo")
            price = instrument.manual_price if instrument else None
            price_input = ui.input("Cena ręczna", value="" if price is None else format_exact(price))
            price_input.props('hint="W walucie notowania; zostaw puste, jeśli cena ma pochodzić ze źródeł wycen"')
            price_input.classes("w-full").mark("instrument-price")
            error = ui.label().classes("text-negative").mark("instrument-error")

            def save() -> None:
                try:
                    manual_price = _parse_price(price_input.value)
                    if asset_class.value is None:
                        raise InstrumentError("Wybierz klasę aktywów.")
                    draft = InstrumentDraft(
                        name=name.value,
                        asset_class_id=asset_class.value,
                        quote_currency=currency.value,
                        market=market.value,
                        manual_price=manual_price,
                        # Symbols in sources without a field here are kept
                        source_symbols={**symbols, YAHOO: yahoo.value},
                    )
                    if instrument is None:
                        add_instrument(self.engine, draft)
                    else:
                        update_instrument(self.engine, instrument.id, draft)
                except InstrumentError as exc:
                    error.text = str(exc)
                    return
                dialog.close()
                self.refresh()

            def delete() -> None:
                if instrument is None:
                    return
                try:
                    delete_instrument(self.engine, instrument.id)
                except InstrumentError as exc:
                    error.text = str(exc)
                    return
                dialog.close()
                self.refresh()

            with ui.row().classes("w-full justify-between"):
                if instrument is not None:
                    ui.button("Usuń", icon="delete", on_click=delete).props("flat color=negative no-caps").mark(
                        "delete-instrument"
                    )
                else:
                    ui.space()
                with ui.row():
                    ui.button("Anuluj", on_click=dialog.close).props("flat")
                    ui.button("Zapisz", on_click=save)
        dialog.open()


def _parse_price(text: str) -> Decimal | None:
    """Read a Manual Price typed the Polish way ("12 850,5"); empty means none."""
    if not text.strip():
        return None
    try:
        return parse_number(text)
    except ValueError:
        raise InstrumentError(f"Cena ręczna musi być liczbą, a nie „{text.strip()}”.") from None
