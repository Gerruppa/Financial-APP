"""Ustawienia > Klasy aktywów and Instrumenty: the editable Asset Classes and the Instrument catalog (spec 3.2)."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from nicegui import run, ui
from sqlalchemy import Engine

from financial_app.domain.bonds import BondSeries
from financial_app.domain.formatting import (
    format_count,
    format_date,
    format_exact,
    format_percent,
    format_quantity,
    format_unit_price,
)
from financial_app.domain.instrument_search import (
    FormFields,
    FoundListing,
    FoundListings,
    InstrumentSearch,
    InstrumentSearchError,
    fill_empty,
)
from financial_app.domain.instruments import (
    MAX_QUANTITY_DECIMALS,
    AssetClass,
    DistributionPolicy,
    Instrument,
    InstrumentDraft,
    InstrumentError,
    parse_optional_number,
)
from financial_app.domain.prices import (
    ANALIZY,
    BANKIER,
    BOSSA,
    FALLBACK_SOURCES,
    MANUAL_PRICE_CLASSES,
    SOURCE_NAMES,
    STAGE_3_CLASSES,
    STOOQ,
    YAHOO,
    FallbackOrderError,
    Quote,
    symbol_in,
    without_fund_code_copy,
)
from financial_app.persistence.bond_series import list_bond_series
from financial_app.persistence.instruments import (
    add_asset_class,
    add_instrument,
    delete_asset_class,
    delete_instrument,
    list_asset_classes,
    list_instruments,
    new_class_fallback_order,
    update_asset_class,
    update_instrument,
)
from financial_app.sources.prices import PriceSource, SymbolCheck, check_symbol
from financial_app.ui.bond_series import open_rates_dialog, rates_summary
from financial_app.ui.dialogs import movable_dialog
from financial_app.ui.fund_details import fund_details
from financial_app.ui.multi_asset import split_editor


@dataclass
class AssetClassesSection:
    """The Klasy aktywów card, with each class's Fallback Order (spec 4.1); ``on_changed`` lets other sections redraw a
    new name or what a changed order prices."""

    engine: Engine
    on_changed: Callable[[], None]

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
            with ui.row().classes("w-full items-center no-wrap border-b py-1").mark(f"asset-class-{asset_class.id}"):
                ui.label(asset_class.name).classes("grow")
                ui.label(_order_text(asset_class.fallback_order)).classes("text-sm k-muted")
                ui.button(icon="edit", on_click=lambda c=asset_class: self.open_dialog(c)).props(
                    f'flat round dense aria-label="Edytuj klasę {asset_class.name}"'
                ).mark(f"edit-asset-class-{asset_class.id}")

    def open_dialog(self, asset_class: AssetClass | None) -> None:
        """Open a form for a new Asset Class (``None``) or for editing ``asset_class``: its name and Fallback Order."""
        order = list(new_class_fallback_order(self.engine) if asset_class is None else asset_class.fallback_order)
        dialog = movable_dialog()
        dialog.on("hide", dialog.delete)
        with dialog, ui.card().classes("w-[400px]"):
            ui.label("Nowa klasa aktywów" if asset_class is None else "Edytuj klasę").classes("text-lg font-bold")
            name = ui.input("Nazwa", value=asset_class.name if asset_class else "").classes("w-full")
            name.mark("asset-class-name")
            ui.label("Kolejność źródeł wycen").classes("font-medium")
            ui.label("Instrument jest wyceniany z pierwszego źródła, dla którego ma symbol.").classes("text-sm k-muted")
            with ui.column().classes("w-full gap-1").mark("fallback-order-editor"):
                _order_editor(order)
            error = ui.label().classes("text-negative").mark("asset-class-error")

            def save() -> None:
                try:
                    if asset_class is None:
                        add_asset_class(self.engine, name.value, order)
                    else:
                        update_asset_class(self.engine, asset_class.id, name.value, order)
                except (InstrumentError, FallbackOrderError) as exc:
                    error.text = str(exc)
                    return
                dialog.close()
                self.class_list.refresh()
                if asset_class is not None:
                    self.on_changed()

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
                self.on_changed()

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


def _order_text(order: Sequence[str]) -> str:
    return " → ".join(SOURCE_NAMES.get(source, source) for source in order) or "bez źródeł"


def _order_editor(order: list[str]) -> None:
    """The Fallback Order being edited, changed in place: each source with buttons to move or remove it, then a button
    for each Price Source not in it yet. Each dialog has its own editor, so a refresh redraws only that one."""

    @ui.refreshable
    def editor() -> None:
        def change(edit: Callable[[], object]) -> None:
            edit()
            editor.refresh()

        def swap(i: int) -> None:
            order[i], order[i + 1] = order[i + 1], order[i]

        if not order:
            ui.label("Bez źródeł: instrumenty tej klasy mają tylko cenę ręczną.").classes("text-sm k-muted")
        for i, source in enumerate(order):
            name = SOURCE_NAMES.get(source, source)
            with ui.row().classes("w-full items-center no-wrap gap-1"):
                ui.label(f"{i + 1}. {name}").classes("grow")
                up = ui.button(icon="arrow_upward", on_click=lambda i=i: change(lambda: swap(i - 1)))
                up.props(f'flat round dense aria-label="Przesuń {name} wyżej"').mark(f"move-up-{source}")
                up.set_enabled(i > 0)
                down = ui.button(icon="arrow_downward", on_click=lambda i=i: change(lambda: swap(i)))
                down.props(f'flat round dense aria-label="Przesuń {name} niżej"').mark(f"move-down-{source}")
                down.set_enabled(i < len(order) - 1)
                ui.button(icon="close", on_click=lambda i=i: change(lambda: order.pop(i))).props(
                    f'flat round dense aria-label="Usuń {name}"'
                ).mark(f"remove-source-{source}")
        with ui.row().classes("gap-1"):
            for source in FALLBACK_SOURCES:
                if source not in order:
                    ui.button(
                        f"+ {SOURCE_NAMES[source]}", on_click=lambda s=source: change(lambda: order.append(s))
                    ).props("flat dense no-caps size=sm").mark(f"add-source-{source}")

    editor()


@dataclass
class InstrumentsSection:
    """The Instrumenty card; ``refresh`` redraws the catalog after a save or an Asset Class rename, and calls
    ``on_changed`` so that other sections redraw too. ``search`` fills the Instrument dialog from a listing found by
    ISIN, name or symbol, and ``sources`` give the "Sprawdź" button beside each Source Symbol one Quote (spec 4.1)."""

    engine: Engine
    search: InstrumentSearch
    sources: Mapping[str, PriceSource]
    on_changed: Callable[[], None]

    def refresh(self) -> None:
        self.instrument_list.refresh()
        self.on_changed()

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
            ui.label("Nie dodano jeszcze żadnego instrumentu.").classes("k-muted")
        bond_series = list_bond_series(self.engine)
        for instrument in instruments:
            self._instrument_row(instrument, bond_series.get(instrument.id))

    def _instrument_row(self, instrument: Instrument, series: BondSeries | None) -> None:
        """The Instrument's details; a Bond Series also shows its rates, with a button to correct them."""
        with ui.row().classes("w-full items-center no-wrap border-b py-1"):
            with ui.column().classes("gap-0 grow"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(instrument.name).classes("font-medium")
                    ui.badge(instrument.asset_class_name).props("outline")
                details = [instrument.quote_currency, instrument.market, instrument.isin]
                if instrument.manual_price is not None:
                    details.append(f"cena ręczna {format_exact(instrument.manual_price)} {instrument.quote_currency}")
                if instrument.metal_grams is not None:
                    details.append(f"metal {format_quantity(instrument.metal_grams)} g")
                if instrument.buyback_spread_percent is not None:
                    details.append(f"spread odkupu {format_percent(instrument.buyback_spread_percent)}")
                details.extend(fund_details(instrument))
                for source, symbol in instrument.source_symbols.items():
                    details.append(f"{SOURCE_NAMES.get(source, source)} {symbol}")
                ui.label(" · ".join(d for d in details if d)).classes("text-sm k-muted")
                if series is not None:
                    ui.label(rates_summary(series)).classes("text-sm k-muted").mark("bond-rates")
            if series is not None:
                ui.button(icon="percent", on_click=lambda: open_rates_dialog(self.engine, series, self.refresh)).props(
                    f'flat round aria-label="Oprocentowanie {instrument.name}"'
                ).mark("edit-bond-rates")
            ui.button(icon="edit", on_click=lambda: self.open_dialog(instrument)).props(
                f'flat round aria-label="Edytuj {instrument.name}"'
            ).mark("edit-instrument")

    def _symbol_check(
        self, field: str, sources: Sequence[str], symbols: Callable[[], Mapping[str, str]], currency: ui.input
    ) -> None:
        """The "Sprawdź" button under ``field``'s Source Symbol field and the lines it shows for each of ``sources``
        (named when there are two, as for the Fund Code): the Quote with its currency and day, a warning when the
        source quotes in another currency than the one typed, or why there is no Quote. ``symbols`` gives the form's
        Source Symbols; each source is checked with its own, bankier.pl falling back to the Fund Code. Nothing is
        saved, so the Instrument saves whatever the check found."""
        checked = [(source, self.sources[source]) for source in sources if source in self.sources]
        if not checked:
            return
        with ui.row().classes("w-full items-center no-wrap gap-2 -mt-2"):
            button = ui.button("Sprawdź").props("flat dense no-caps size=sm").mark(f"check-symbol-{field}")
            result = ui.column().classes("gap-0 text-sm").mark(f"symbol-check-{field}")

        def check_all(typed: Mapping[str, str], currency: str) -> list[SymbolCheck]:
            return [check_symbol(price_source, symbol_in(source, typed), currency) for source, price_source in checked]

        async def check() -> None:
            result.clear()
            button.props("loading")
            try:
                # The sources answer over the network, so the window keeps working meanwhile
                found = await run.io_bound(check_all, symbols(), currency.value)
            finally:
                button.props(remove="loading")
            if found is None:  # the app is shutting down
                return
            with result:
                for (source, _), one in zip(checked, found, strict=True):
                    prefix = f"{SOURCE_NAMES[source]}: " if len(checked) > 1 else ""
                    if one.quote is not None:
                        ui.label(prefix + _quote_text(one.quote))
                    if one.warning:
                        ui.label(prefix + one.warning).classes("text-warning")
                    if one.error:
                        ui.label(prefix + one.error).classes("text-negative")

        button.on_click(check)

    def open_dialog(
        self,
        instrument: Instrument | None,
        *,
        query: str = "",
        prefill: FoundListing | None = None,
        on_saved: Callable[[Instrument], None] | None = None,
    ) -> None:
        """Open a fresh form for a new Instrument (``None``) or for editing ``instrument``. A new one's search starts
        from ``query`` (e.g. an imported ticker), or its empty fields are filled from ``prefill`` as if chosen among
        the results (the Instrument Card's "Dodaj jako instrument", issue #175); ``on_saved`` gets the saved
        Instrument."""
        dialog = movable_dialog()
        dialog.on("hide", dialog.delete)
        asset_classes = list_asset_classes(self.engine)
        class_options = {c.id: c.name for c in asset_classes}
        with dialog, ui.card().classes("w-[480px]").mark("instrument-dialog"):
            ui.label("Nowy instrument" if instrument is None else "Edytuj instrument").classes("text-lg font-bold")
            # An Instrument without Source Symbols (e.g. imported as "ISAC") is searched by its name
            query = instrument.name if instrument and not instrument.source_symbols else query
            with ui.row().classes("w-full items-center no-wrap"):
                search_input = ui.input("Szukaj (ISIN, nazwa lub symbol)", value=query).classes("grow")
                search_input.mark("instrument-search")
                search_button = ui.button(icon="search").props('flat round aria-label="Szukaj instrumentu"')
                search_button.mark("instrument-search-button")
            search_results = ui.column().classes("w-full gap-0")
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
            isin = ui.input("ISIN", value=instrument.isin if instrument else "")
            isin.props('hint="Np. IE00B6R52259; może zostać puste"').classes("w-full").mark("instrument-isin")
            # A bankier.pl symbol only repeating the Fund Code is dropped, as bankier.pl uses the Fund Code anyway
            symbols = without_fund_code_copy(instrument.source_symbols) if instrument else {}
            class_orders = {c.id: c.fallback_order for c in asset_classes}
            # The Asset Class's sources first, in its Fallback Order, the Fund Code field standing for analizy.pl and
            # bankier.pl; the others wait under "Więcej źródeł" and keep their symbols, and Stooq, which never values
            # a Position, has its own section
            with ui.column().classes("w-full gap-2").mark("class-sources"):
                note = ui.label().classes("text-sm k-muted").mark("class-sources-note")
                class_sources = ui.column().classes("w-full gap-2")
            more = ui.expansion().classes("w-full").mark("more-sources")
            stooq_section = ui.expansion("Historia notowań (Stooq)").classes("w-full").mark("stooq-history")
            fields: dict[str, ui.column] = {}
            symbol_inputs: dict[str, ui.input] = {}
            more_sources: list[str] = []

            def typed_symbols() -> dict[str, str]:
                # A cleared field's value is None
                return {source: field.value or "" for source, field in symbol_inputs.items()}

            for source, (label, hint) in _SYMBOL_FIELDS.items():
                with stooq_section if source == STOOQ else more, ui.column().classes("w-full gap-2") as field:
                    symbol_input = ui.input(label, value=symbols.get(source, ""))
                    symbol_input.props(f'hint="{hint}"').classes("w-full").mark(f"instrument-symbol-{source}")
                    if source != STOOQ:  # history only, it gives no Quote to check
                        checked = (ANALIZY, BANKIER) if source == ANALIZY else (source,)
                        self._symbol_check(source, checked, typed_symbols, currency)
                fields[source], symbol_inputs[source] = field, symbol_input

            def count_more() -> None:
                typed = typed_symbols()
                filled = sum(1 for source in more_sources if typed[source].strip())
                more.text = f"Więcej źródeł ({format_count(filled, 'wypełniony', 'wypełnione', 'wypełnionych')})"

            def arrange() -> None:
                order = class_orders.get(asset_class.value, ())
                # The Fund Code (the analizy.pl field) stands where the first of analizy.pl and bankier.pl is; a
                # bankier.pl symbol of its own is needed only when its code differs, so it waits under "Więcej źródeł"
                shown = list(dict.fromkeys(ANALIZY if source == BANKIER else source for source in order))
                for i, source in enumerate(shown):
                    fields[source].move(class_sources, target_index=i)
                more_sources[:] = [source for source in FALLBACK_SOURCES if source not in shown]
                for source in more_sources:
                    fields[source].move(more)
                note.visible = not shown
                if not shown:
                    note.text = _no_sources_note(class_options.get(asset_class.value))
                more.visible = bool(more_sources)
                count_more()

            for symbol_input in symbol_inputs.values():
                symbol_input.on_value_change(count_more)
            asset_class.on_value_change(arrange)
            arrange()
            decimals = ui.select(
                {places: str(places) for places in range(MAX_QUANTITY_DECIMALS + 1)},
                label="Miejsca po przecinku w liczbie",
                value=instrument.quantity_decimals if instrument else 0,
            ).classes("w-full")
            decimals.props('hint="Np. 8 dla kryptowalut; zaokrągla liczbę proponowaną z kwoty do wydania"')
            decimals.mark("instrument-quantity-decimals")
            price = instrument.manual_price if instrument else None
            price_input = ui.input("Cena ręczna", value="" if price is None else format_exact(price))
            price_input.props(
                'hint="W walucie notowania (metal z wagą: spot za uncję); '
                'zostaw puste, jeśli cena ma pochodzić ze źródeł wycen"'
            )
            price_input.classes("w-full").mark("instrument-price")
            grams = instrument.metal_grams if instrument else None
            grams_input = ui.input("Waga metalu w jednostce (g)", value=_exact_text(grams))
            grams_input.props(
                'hint="Metale fizyczne: np. 31,1034768 dla monety 1 oz; cena jest wtedy spotem za uncję. '
                'Zostaw puste dla zwykłej ceny za jednostkę"'
            )
            grams_input.classes("w-full").mark("instrument-metal-grams")
            spread = instrument.buyback_spread_percent if instrument else None
            spread_input = ui.input("Spread odkupu %", value=_exact_text(spread))
            spread_input.props('hint="O ile poniżej spotu odkupuje dealer, np. 5"')
            spread_input.classes("w-full").mark("instrument-buyback-spread")
            ter = instrument.ter_percent if instrument else None
            ter_input = ui.input("TER %", value=_exact_text(ter))
            ter_input.props('hint="Roczny koszt funduszu, np. 0,07; może zostać puste"')
            ter_input.classes("w-full").mark("instrument-ter")
            policy = ui.select(
                {p: p.label for p in DistributionPolicy},
                label="Polityka dywidendowa",
                value=instrument.distribution_policy if instrument else None,
                clearable=True,
            ).classes("w-full")
            policy.mark("instrument-distribution-policy")
            domicile = ui.input("Siedziba funduszu", value=instrument.domicile if instrument else "")
            domicile.props('hint="Np. Irlandia, Luksemburg; może zostać puste"').classes("w-full")
            domicile.mark("instrument-domicile")
            # Only a Multi-asset Instrument is split across classes; one moved to another class loses its split
            multi_asset_classes = {c.id for c in asset_classes if c.multi_asset}
            with ui.column().classes("w-full") as split_section:
                typed_split = split_editor(asset_classes, instrument.multi_asset_split if instrument else {})

            def show_split() -> None:
                split_section.visible = asset_class.value in multi_asset_classes

            asset_class.on_value_change(show_split)
            show_split()
            error = ui.label().classes("text-negative").mark("instrument-error")

            def choose(result: FoundListing) -> None:
                # A new Instrument's default PLN was not typed by the user, so a listing's own currency replaces it
                untouched_default = instrument is None and currency.value == "PLN"
                filled = fill_empty(
                    FormFields(
                        name=name.value or "",
                        isin=isin.value or "",
                        quote_currency="" if untouched_default else currency.value or "",
                        market=market.value or "",
                        source_symbols=typed_symbols(),
                        asset_class=class_options.get(asset_class.value, ""),
                        domicile=domicile.value or "",
                        distribution_policy=policy.value,
                    ),
                    result,
                )
                name.value, isin.value, market.value = filled.name, filled.isin, filled.market
                domicile.value, policy.value = filled.domicile, filled.distribution_policy
                currency.value = filled.quote_currency or currency.value
                for source, field in symbol_inputs.items():
                    field.value = filled.source_symbols[source]
                # The class is matched by name, whatever its case; a class the user does not have is left unset
                if asset_class.value is None:
                    wanted = filled.asset_class.casefold()
                    asset_class.value = next((i for i, n in class_options.items() if n.casefold() == wanted), None)
                search_results.clear()

            async def find() -> None:
                search_results.clear()
                search_button.props("loading")
                try:
                    # The search answers over the network, so the window keeps working meanwhile
                    found = await run.io_bound(self.search.search, search_input.value)
                    # An empty FoundListings still carries its notes, so only None (shutting down) counts as nothing
                    results = [] if found is None else found
                    # A search service that failed beside the others is noted above their results
                    notes = results.notes if isinstance(results, FoundListings) else []
                    message = " · ".join(notes) if results else " · ".join(["Nic nie znaleziono.", *notes])
                except InstrumentSearchError as exc:
                    results, message = [], str(exc)
                finally:
                    search_button.props(remove="loading")
                with search_results:
                    if message:
                        ui.label(message).classes("text-sm k-muted").mark("instrument-search-message")
                    for result in results:
                        _result_row(result, choose)

            search_button.on_click(find)
            search_input.on("keydown.enter", find)
            if prefill is not None:
                choose(prefill)

            def save() -> None:
                try:
                    manual_price = parse_optional_number(price_input.value, "Cena ręczna")
                    metal_grams = parse_optional_number(grams_input.value, "Waga metalu")
                    buyback_spread = parse_optional_number(spread_input.value, "Spread odkupu")
                    ter_percent = parse_optional_number(ter_input.value, "TER")
                    if asset_class.value is None:
                        raise InstrumentError("Wybierz klasę aktywów.")
                    draft = InstrumentDraft(
                        name=name.value,
                        asset_class_id=asset_class.value,
                        quote_currency=currency.value,
                        market=market.value,
                        isin=isin.value,
                        manual_price=manual_price,
                        # Symbols in sources without a field here are kept
                        source_symbols=without_fund_code_copy({**symbols, **typed_symbols()}),
                        metal_grams=metal_grams,
                        buyback_spread_percent=buyback_spread,
                        ter_percent=ter_percent,
                        distribution_policy=policy.value,
                        domicile=domicile.value,
                        multi_asset_split=typed_split() if split_section.visible else {},
                        quantity_decimals=decimals.value,
                    )
                    if instrument is None:
                        saved = add_instrument(self.engine, draft)
                    else:
                        saved = update_instrument(self.engine, instrument.id, draft)
                except InstrumentError as exc:
                    error.text = str(exc)
                    return
                dialog.close()
                self.refresh()
                if on_saved is not None:
                    on_saved(saved)

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


# Each Source Symbol field's label and hint, in the order the fields outside the Asset Class's sources are listed
_SYMBOL_FIELDS = {
    YAHOO: ("Symbol Yahoo", "Np. ISAC.L, AAPL, BTC-USD; zostaw puste, jeśli Yahoo nie notuje instrumentu"),
    BOSSA: ("Symbol Bossa", "Np. PZU, CDR, ETFBDIVPL; zostaw puste, jeśli instrumentu nie ma na GPW"),
    # The Fund Code, shared by analizy.pl and bankier.pl, is saved as the analizy.pl Source Symbol
    ANALIZY: (
        "Kod funduszu",
        "Fundusze i PPK: kod z adresu strony funduszu, np. PZU60 z analizy.pl/fundusze/ppk/PZU60",
    ),
    BANKIER: (
        "Symbol bankier.pl (gdy inny niż kod funduszu)",
        "Zwykle puste, bo bankier.pl używa kodu funduszu; wpisz, gdy kod w bankier.pl jest inny",
    ),
    STOOQ: ("Symbol Stooq", "Tylko historia notowań (wykresy, benchmarki), np. wig, swig80tr, cdr; nie wycenia"),
}


def _no_sources_note(class_name: str | None) -> str:
    """Where the price comes from when the Asset Class (``None``: not chosen yet) has no Price Sources."""
    if class_name is None:
        return "Wybierz klasę aktywów, żeby zobaczyć źródła wycen."
    if class_name in STAGE_3_CLASSES:
        return (
            "Serie obligacji detalicznych są wyceniane z danych MF; inne obligacje skarbowe (Catalyst) wyceni Bossa, "
            "gdy dodasz ją w Ustawienia > Klasy aktywów, albo cena ręczna."
        )
    if class_name in MANUAL_PRICE_CLASSES:
        return "Ta klasa nie ma źródeł wycen: podaj cenę ręczną."
    return "Ta klasa nie ma źródeł wycen. Dodaj je w Ustawienia > Klasy aktywów albo podaj cenę ręczną."


def _quote_text(quote: Quote) -> str:
    """A checked Quote, e.g. "45,12 zł · 09.10.2026"."""
    return f"{format_unit_price(quote.price, quote.currency)} · {format_date(quote.day)}"


def _result_row(result: FoundListing, choose: Callable[[FoundListing], None]) -> None:
    """One listing found; clicking it fills the form's empty fields."""
    details = " · ".join(
        d for d in [result.source, result.market, result.symbol, result.currency or "waluta nieznana"] if d
    )
    item = ui.item(on_click=lambda: choose(result)).classes("w-full rounded").mark(f"search-result-{result.symbol}")
    with item, ui.item_section():
        ui.item_label(result.name)
        ui.item_label(details).props("caption")


def _exact_text(number: Decimal | None) -> str:
    return "" if number is None else format_exact(number)
