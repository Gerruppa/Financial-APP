"""The price source help window of an Instrument without a price (issue #274), opened from its row in Ustawienia >
Instrumenty bez wyceny: which Price Sources fit it and how to find its symbol (``domain/price_source_guide.py``), a
"Sprawdź" that fetches one Quote with the typed symbol (``check_symbol``, as in the Instrument dialog), then saving the
Source Symbol on the Instrument, or a Manual Price when no source quotes it."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace

from nicegui import run, ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_date, format_exact, format_unit_price
from financial_app.domain.instruments import Instrument, InstrumentError, parse_optional_number
from financial_app.domain.price_source_guide import (
    MANUAL_HELP,
    SOURCE_HELP,
    SourceAdvice,
    SourceHelp,
    advised_sources,
)
from financial_app.domain.prices import SOURCE_NAMES, without_fund_code_copy
from financial_app.persistence.instruments import get_instrument, update_instrument
from financial_app.sources.prices import PriceSource, SymbolCheck, check_symbol
from financial_app.ui.wizard import Wizard, WizardStep

# The choice of a Manual Price instead of a Price Source
MANUAL = "manual"


@dataclass
class PriceSourceGuide:
    """The window for one Instrument and what the user chose in it; ``on_saved`` runs after the Instrument is saved.
    Made inside an element that outlives the unpriced list, which redraws once the Instrument is saved."""

    engine: Engine
    sources: Mapping[str, PriceSource]
    instrument: Instrument
    on_saved: Callable[[], object]
    # A Price Source, MANUAL, or "" before the user chooses
    choice: str = ""
    symbol: str = ""
    # The last check and the symbol it checked; "Dalej" follows a Quote for the symbol still typed
    check: SymbolCheck | None = None
    checked_symbol: str = ""
    price: str = ""
    saved: bool = False
    error: str = ""
    wizard: Wizard = field(init=False)

    def __post_init__(self) -> None:
        steps = (
            WizardStep("Wybierz źródło ceny", self._choose),
            WizardStep("Symbol albo cena ręczna", self._details),
            WizardStep("Podsumowanie", self._review),
        )
        self.wizard = Wizard("price-guide", steps, width="w-[44rem]")
        self.wizard.dialog.on("hide", self.wizard.dialog.delete)

    def open(self) -> None:
        self.wizard.open()

    @property
    def _name(self) -> str:
        return SOURCE_NAMES.get(self.choice, self.choice)

    def _pick(self, choice: str) -> None:
        if choice != self.choice:
            self.choice = choice
            self.symbol = self.instrument.source_symbols.get(choice, "")
            self.check, self.checked_symbol, self.error = None, "", ""
        self.wizard.go(2)

    def _choose(self) -> bool:
        instrument = self.instrument
        facts = [
            instrument.instrument_type.label,
            instrument.asset_class_name,
            instrument.market,
            instrument.quote_currency,
        ]
        ui.label(f"{instrument.name} · {' · '.join(fact for fact in facts if fact)}").classes("font-medium")
        ui.label(
            "Ceny pobiera się ze źródeł, które klasa aktywów instrumentu ma w kolejności wycen. Wybierz źródło, "
            "które notuje ten instrument, albo podaj cenę ręczną."
        ).classes("text-sm k-muted")
        for advice in advised_sources(instrument):
            self._source_row(advice)
        with ui.row().classes("w-full items-center no-wrap gap-2 border-t pt-2"):
            with ui.column().classes("grow gap-0"):
                ui.label("Cena ręczna").classes("font-bold")
                ui.label(MANUAL_HELP).classes("text-sm")
            _pick_button(self.choice == MANUAL, lambda: self._pick(MANUAL)).mark("price-guide-source-manual")
        return bool(self.choice)

    def _source_row(self, advice: SourceAdvice) -> None:
        name = SOURCE_NAMES[advice.source]
        with ui.row().classes("w-full items-center no-wrap gap-2 border-t pt-2"):
            with ui.column().classes("grow gap-0"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(name).classes("font-bold")
                    if advice.fits:
                        ui.badge("pasuje").props("outline color=positive")
                ui.label(advice.help.why).classes("text-sm")
                _examples(advice.help).classes("text-xs")
                if not advice.in_order:
                    ui.label(
                        f"Klasa „{self.instrument.asset_class_name}” nie pobiera cen z {name}: dodaj to źródło "
                        "w Ustawienia > Klasy aktywów i wróć tutaj."
                    ).classes("text-xs text-warning")
            if advice.in_order:
                _pick_button(self.choice == advice.source, lambda: self._pick(advice.source)).mark(
                    f"price-guide-source-{advice.source}"
                )

    def _details(self) -> bool:
        # Back from the summary, a new symbol or price waits for its own save
        self.saved = False
        if self.choice == MANUAL:
            return self._manual_price()
        source_help = SOURCE_HELP[self.choice]
        ui.label(source_help.find).classes("text-sm")
        _examples(source_help).classes("text-sm")
        symbol = ui.input(f"Symbol {self._name}", value=self.symbol).classes("w-full").mark("price-guide-symbol")
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            button = ui.button("Sprawdź").props("no-caps").mark("price-guide-check")
            result = ui.column().classes("gap-0 text-sm").mark("price-guide-result")
        if self.check is not None:
            with result:
                _check_lines(self.check)

        def typed_symbol(text: str | None) -> None:
            self.symbol = (text or "").strip()
            if self.check is not None and self.symbol != self.checked_symbol:
                self.check, self.checked_symbol = None, ""
                result.clear()
                self.wizard.set_ready(False)

        async def check() -> None:
            result.clear()
            button.props("loading")
            source, checked = self.sources.get(self.choice), self.symbol
            try:
                # The source answers over the network, so the window keeps working meanwhile
                found = (
                    SymbolCheck(error=f"Źródło {self._name} jest niedostępne.")
                    if source is None
                    else await run.io_bound(check_symbol, source, checked, self.instrument.quote_currency)
                )
            finally:
                button.props(remove="loading")
            if found is None:  # the app is shutting down
                return
            self.check, self.checked_symbol = found, checked
            with result:
                _check_lines(found)
            self.wizard.set_ready(self._checked())

        symbol.on_value_change(lambda event: typed_symbol(event.value))
        button.on_click(check)
        return self._checked()

    def _checked(self) -> bool:
        """A Quote in the Instrument's currency for the symbol typed: one the price refresh will fetch too."""
        found = self.check
        return (
            found is not None and found.quote is not None and not found.warning and self.symbol == self.checked_symbol
        )

    def _manual_price(self) -> bool:
        metal = " za uncję trojańską" if self.instrument.metal_grams is not None else ""
        ui.label(
            f"Wpisz cenę jednej jednostki{metal} w {self.instrument.quote_currency}. Zmienisz ją później "
            "w oknie instrumentu w Ustawienia > Instrumenty."
        ).classes("text-sm")
        price = ui.input(f"Cena ręczna ({self.instrument.quote_currency})", value=self.price).mark("price-guide-price")
        problem = ui.label().classes("text-negative text-sm").mark("price-guide-price-error")

        def typed_price(text: str | None) -> None:
            self.price = text or ""
            problem.text = self._price_problem()
            self.wizard.set_ready(self._price_ok())

        price.on_value_change(lambda event: typed_price(event.value))
        problem.text = self._price_problem()
        return self._price_ok()

    def _price_problem(self) -> str:
        """Why the typed price is not a number, in Polish; "" while it is one or nothing is typed."""
        try:
            parse_optional_number(self.price, "Cena ręczna")
        except InstrumentError as error:
            return str(error)
        return ""

    def _price_ok(self) -> bool:
        return not self._price_problem() and bool(self.price.strip())

    def _review(self) -> bool:
        currency = self.instrument.quote_currency
        if self.choice == MANUAL:
            price = parse_optional_number(self.price, "Cena ręczna")
            ui.label(f"Cena ręczna: {'' if price is None else format_exact(price)} {currency}").classes("font-medium")
        else:
            ui.label(f"{self._name}: symbol {self.checked_symbol}").classes("font-medium")
        if self.saved:
            with ui.column().classes("gap-1").mark("price-guide-saved"):
                ui.label("Zapisano.").classes("text-positive font-bold")
                ui.label(
                    "Instrument ma cenę ręczną; zostaje na liście bez wyceny automatycznej."
                    if self.choice == MANUAL
                    else "Cena pojawi się po odświeżeniu wycen (przycisk odświeżania w nagłówku)."
                ).classes("text-sm")
            return True
        ui.button("Zapisz", on_click=self._save).props("no-caps").mark("price-guide-save")
        if self.error:
            ui.label(self.error).classes("text-negative")
        return True

    def _save(self) -> None:
        # Fresh, so a change made in the Instrument dialog meanwhile is kept
        instrument = get_instrument(self.engine, self.instrument.id)
        try:
            if self.choice == MANUAL:
                draft = replace(instrument, manual_price=parse_optional_number(self.price, "Cena ręczna"))
            else:
                symbols = without_fund_code_copy({**instrument.source_symbols, self.choice: self.checked_symbol})
                draft = replace(instrument, source_symbols=symbols)
            self.instrument = update_instrument(self.engine, instrument.id, draft)
        except InstrumentError as error:
            self.error = str(error)
            self.wizard.render()
            return
        self.saved, self.error = True, ""
        self.wizard.render()
        self.on_saved()


def _pick_button(chosen: bool, pick: Callable[[], None]) -> ui.button:
    return ui.button("Wybrano" if chosen else "Wybierz", on_click=pick).props(
        "no-caps" if chosen else "outline no-caps"
    )


def _examples(source_help: SourceHelp) -> ui.label:
    return ui.label(f"Przykłady: {', '.join(source_help.examples)}").classes("k-muted")


def _check_lines(found: SymbolCheck) -> None:
    """The checked Quote with its day, a warning when it is in another currency, or why there is none."""
    if found.quote is not None:
        ui.label(f"{format_unit_price(found.quote.price, found.quote.currency)} · {format_date(found.quote.day)}")
    if found.warning:
        ui.label(found.warning).classes("text-warning")
    if found.error:
        ui.label(found.error).classes("text-negative")
