"""Investment Strategies (issue #76, spec 5): the Strategie inwestycyjne tab, where the View Scope's Allocation Targets
with their tolerance bands and the Instrument Targets are edited, the Dashboard's Strategia inwestycyjna section, and
the notice after a price refresh naming the classes outside their band.

Total's strategy is edited in Total; an Account's own in its scope, once created. The Planned Deposit ("Planuję
wpłacić") is shared by the tab and the Dashboard of a window and never saved.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.formatting import (
    format_exact,
    format_percent,
    format_pln,
    format_points,
    format_quantity,
    parse_number,
)
from financial_app.domain.instruments import AssetClass, Instrument, InstrumentError, parse_optional_number
from financial_app.domain.strategy import (
    DEFAULT_BAND,
    BandStatus,
    ClassRow,
    ClassTarget,
    Strategy,
    StrategyError,
    StrategyView,
    deposit_accounts,
    strategy_view,
)
from financial_app.persistence.instruments import list_asset_classes
from financial_app.persistence.strategies import delete_strategy, list_strategies, save_strategy
from financial_app.sources.dashboard import TodaysDashboard, todays_dashboard
from financial_app.sources.nbp import NbpRates
from financial_app.ui.changes import TODAYS_VALUE
from financial_app.ui.dialogs import movable_dialog
from financial_app.ui.info import info_icon
from financial_app.ui.view_scope import ViewScope

STATUS_COLOURS = {BandStatus.GREEN: "bg-green-1", BandStatus.YELLOW: "bg-amber-2", BandStatus.RED: "bg-red-2"}
ROW_COLUMNS = "grid-template-columns: minmax(10rem, 2fr) repeat(6, minmax(6rem, 1fr)) minmax(8rem, 1.5fr)"
ROW_HEADERS = ("Klasa", "Wartość", "Udział", "Cel", "Różnica", "Do celu", "Z wpłaty", "")


@dataclass
class PlannedDeposit:
    """The amount the user plans to deposit, shared by the tab and the Dashboard of one window."""

    amount: Decimal = Decimal(0)


@dataclass(frozen=True)
class ScopeStrategy:
    """The View Scope's Investment Strategy (``None``: Total without one or an Account without its own) and its
    view today, with the active Accounts each class to buy could be bought on (Total only) and the Asset Classes."""

    strategy: Strategy | None
    view: StrategyView
    buy_on: Mapping[str, tuple[int, ...]]
    account_names: Mapping[int, str]
    asset_classes: list[AssetClass]
    instruments: Mapping[int, Instrument]
    planned: Decimal = Decimal(0)


def scope_strategy(engine: Engine, today: TodaysDashboard, account_id: int | None, planned: Decimal) -> ScopeStrategy:
    """The strategy of the View Scope ``account_id`` (``None``: Total) against ``today``'s Dashboard of it."""
    strategies = list_strategies(engine)
    strategy = strategies.get(account_id)
    asset_classes = list_asset_classes(engine)
    board = today.board
    classes = {share.asset_class: share.value for share in board.classes}
    # Without Allocation Targets there is nothing to rebalance toward: only the structure shows
    targeted = strategy if strategy is not None and strategy.class_targets else None
    view = strategy_view(targeted, asset_classes, today.instruments, classes, board.holdings, planned)
    buy_on: Mapping[str, tuple[int, ...]] = {}
    if account_id is None and targeted is not None:
        active = {account.id for account in today.accounts if account.active}
        own = {a: s for a, s in strategies.items() if a in active}
        held = {a: classes for a, classes in board.account_classes.items() if a in active}
        buy_on = deposit_accounts(view, asset_classes, own, held)
    names = {account.id: account.name for account in today.accounts}
    return ScopeStrategy(strategy, view, buy_on, names, asset_classes, today.instruments, planned)


def out_of_band_notice(engine: Engine, rates: NbpRates) -> str | None:
    """The classes outside their tolerance band in Total's strategy and each Account's own, e.g. after a price
    refresh; ``None`` when every class is within its band."""
    strategies = list_strategies(engine)
    if not any(strategy.class_targets for strategy in strategies.values()):
        return None
    parts = []
    for account_id, strategy in sorted(strategies.items(), key=lambda item: (item[0] is not None, item[0] or 0)):
        today = todays_dashboard(engine, rates, account_id)
        current = scope_strategy(engine, today, account_id, Decimal(0))
        outside = [row for row in current.view.rows if row.status in (BandStatus.YELLOW, BandStatus.RED)]
        if outside and strategy.class_targets:
            scope = "Total" if account_id is None else current.account_names.get(account_id, "")
            classes = ", ".join(f"{row.asset_class} ({_difference(row)})" for row in outside)
            parts.append(f"{scope}: {classes}")
    return f"Poza pasmem tolerancji: {'; '.join(parts)}." if parts else None


# Behind the "i" of the Dashboard's Strategia inwestycyjna
STRATEGY_INFO = (
    "Porównanie dzisiejszego udziału każdej klasy aktywów z celem ustawionym w zakładce Strategie inwestycyjne. "
    "Klasa poza dopuszczalnym odchyleniem wymaga rebalansowania.\n\n"
    "Planowana wpłata pokazuje, jak podzielić nowe pieniądze między klasy, żeby zbliżyć portfel do celów bez "
    "sprzedawania czegokolwiek."
)


def strategy_section(
    engine: Engine, today: TodaysDashboard, account_id: int | None, planned: PlannedDeposit
) -> ScopeStrategy:
    """The Dashboard's Strategia inwestycyjna: the class rows with the Planned Deposit's split and a link to the tab
    for the details; it edits no targets. Returns the strategy it shows."""
    with ui.card().classes("w-full").mark("dashboard-strategy"):
        with ui.row().classes("w-full items-center"):
            ui.label("Strategia inwestycyjna").classes("text-lg font-medium grow")
            ui.link("Szczegóły", "/strategie").mark("strategy-details")
            info_icon(STRATEGY_INFO, "strategy")
        return _strategy_body(engine, today, account_id, planned, details=False)


@dataclass
class StrategyPage:
    """The Strategie inwestycyjne tab of the View Scope."""

    # The changes it redraws on (ui/changes.py)
    CHANGES = TODAYS_VALUE

    engine: Engine
    rates: NbpRates
    scope: ViewScope
    planned: PlannedDeposit = field(default_factory=PlannedDeposit)

    def refresh(self) -> None:
        """Redraw the tab if it is on screen (e.g. after a save, a price refresh or a scope change)."""
        self.content.refresh()

    def build(self) -> None:
        ui.label("Strategie inwestycyjne").classes("text-2xl font-bold")
        with ui.column().classes("w-full max-w-screen-2xl").mark("strategy"):
            self.content()

    @ui.refreshable_method
    def content(self) -> None:
        account_id = self.scope.account_id
        today = todays_dashboard(self.engine, self.rates, account_id)
        strategy = list_strategies(self.engine).get(account_id)
        with ui.row().classes("items-center gap-2"):
            if account_id is not None and strategy is None:
                name = next((a.name for a in today.accounts if a.id == account_id), "")
                ui.label(
                    f"Konto „{name}” nie ma własnej strategii: poniżej jego struktura bez rebalansowania."
                ).classes("text-gray-500")
                ui.button("Utwórz strategię konta", on_click=lambda: self._save(Strategy(account_id))).mark(
                    "create-strategy"
                )
            else:
                current = strategy or Strategy(account_id)
                ui.button("Edytuj cele klas", on_click=lambda: self._edit_targets(current)).mark("edit-targets")
                if account_id is not None:
                    ui.button("Usuń strategię konta", on_click=self._delete).props("flat color=negative").mark(
                        "delete-strategy"
                    )
        _strategy_body(self.engine, today, account_id, self.planned, details=True, edit=self._edit_instruments)

    def _save(self, strategy: Strategy) -> None:
        save_strategy(self.engine, strategy)
        self.refresh()

    def _delete(self) -> None:
        delete_strategy(self.engine, self.scope.account_id)
        self.refresh()

    def _edit_targets(self, strategy: Strategy) -> None:
        _targets_dialog(list_asset_classes(self.engine), strategy, self._save)

    def _edit_instruments(self, asset_class: AssetClass, instruments: Sequence[Instrument]) -> None:
        strategy = list_strategies(self.engine).get(self.scope.account_id) or Strategy(self.scope.account_id)
        _instrument_targets_dialog(asset_class, instruments, strategy, self._save)


type EditInstruments = Callable[[AssetClass, Sequence[Instrument]], None]


def _strategy_body(
    engine: Engine,
    today: TodaysDashboard,
    account_id: int | None,
    planned: PlannedDeposit,
    details: bool,
    edit: EditInstruments | None = None,
) -> ScopeStrategy:
    """The Planned Deposit field, the deposit needed for full rebalancing and the class rows (with their Instruments
    when showing the ``details``); typing an amount redraws only the rows. Returns the strategy shown."""
    current = scope_strategy(engine, today, account_id, planned.amount)
    if current.view.targets_sum is None:
        if account_id is None:
            ui.label("Brak celów alokacji: ustaw je w zakładce Strategie inwestycyjne.").classes("text-gray-500")
        _class_rows(current, details, edit)
        return current

    @ui.refreshable
    def rows() -> None:
        shown = scope_strategy(engine, today, account_id, planned.amount)
        _rebalancing(shown.view)
        _class_rows(shown, details, edit)

    def typed(text: str) -> None:
        try:
            amount = parse_number(text) if text.strip() else Decimal(0)
        except ValueError:
            return
        if amount >= 0:
            planned.amount = amount
            rows.refresh()

    field_text = format_exact(planned.amount) if planned.amount else ""
    deposit = ui.input("Planuję wpłacić", value=field_text).props('dense suffix="zł"').classes("w-48")
    deposit.mark("planned-deposit").on_value_change(lambda event: typed(event.value or ""))
    if current.view.targets_sum != 100:
        ui.label(f"Cele klas sumują się do {format_percent(current.view.targets_sum)}, a nie do 100%.").classes(
            "text-warning"
        ).mark("targets-sum-warning")
    rows()
    return current


def _rebalancing(view: StrategyView) -> None:
    with ui.row().classes("items-center gap-2 text-sm").mark("rebalancing"):
        ui.label("Wpłata potrzebna do pełnego rebalansowania bez sprzedaży:")
        if view.rebalancing_deposit is None:
            ui.label("niemożliwe bez sprzedaży (klasa bez celu ma wartość)").mark("rebalancing-deposit")
        else:
            ui.label(format_pln(view.rebalancing_deposit)).classes("font-medium").mark("rebalancing-deposit")


def _class_rows(current: ScopeStrategy, details: bool, edit: EditInstruments | None) -> None:
    by_name = {asset_class.name: asset_class for asset_class in current.asset_classes}
    with ui.element("div").classes("grid w-full gap-x-4 border-b py-1 text-sm font-medium").style(ROW_COLUMNS):
        for header in ROW_HEADERS:
            ui.label(header).classes("" if header in ("Klasa", "") else "text-right")
    for row in current.view.rows:
        asset_class = by_name.get(row.asset_class)
        line = ui.element("div").classes("grid w-full gap-x-4 border-b py-1 text-sm items-center").style(ROW_COLUMNS)
        if row.status is not None:
            line.classes(STATUS_COLOURS[row.status])
        with line.mark(f"strategy-row band-{row.status.value}" if row.status else "strategy-row"):
            ui.label(row.asset_class).classes("font-medium")
            ui.label(format_pln(row.value)).classes("text-right")
            ui.label(format_percent(row.share * 100)).classes("text-right")
            target = row.target
            band = f"{format_percent(target.percent)} ± {format_points(target.band, exact=True)}" if target else ""
            ui.label(band).classes("text-right")
            ui.label(_difference(row) if target else "").classes("text-right")
            to_target = "" if row.to_target is None else format_pln(row.to_target, signed=True)
            ui.label(to_target).classes("text-right")
            marker = f"deposit-{asset_class.id}" if asset_class else "deposit"
            shown = row.from_deposit is not None and current.planned > 0
            from_deposit = format_pln(row.from_deposit) if shown and row.from_deposit is not None else ""
            ui.label(from_deposit).classes("text-right").mark(marker)
            names = [current.account_names.get(a, "") for a in current.buy_on.get(row.asset_class, ())]
            accounts = ui.label(f"Kup na: {', '.join(names)}" if names else "").classes("text-gray-600")
            accounts.mark(f"accounts-{asset_class.id}" if asset_class else "accounts")
        if details and asset_class is not None:
            _instrument_rows(row, asset_class, current.instruments, edit)


def _instrument_rows(
    row: ClassRow, asset_class: AssetClass, instruments: Mapping[int, Instrument], edit: EditInstruments | None
) -> None:
    """The class's Instruments, held or targeted, with their part of the deposit, and the button editing their
    Instrument Targets (among the catalog's Instruments of the class)."""
    catalog = [i for i in instruments.values() if i.asset_class_id == asset_class.id]
    if not row.instruments and not catalog:
        return
    with ui.column().classes("w-full pl-8 gap-0").mark(f"instruments-{asset_class.id}"):
        for held in row.instruments:
            with ui.row().classes("w-full items-center text-sm gap-4").mark("instrument-row"):
                ui.label(held.instrument.name).classes("grow")
                ui.label(format_pln(held.value)).classes("w-28 text-right")
                ui.label(format_percent(held.share * 100)).classes("w-20 text-right")
                target = "" if held.target is None else f"cel {format_percent(held.target)}"
                ui.label(target).classes("w-24 text-right")
                deposit = "" if not held.from_deposit else f"z wpłaty {format_pln(held.from_deposit)}"
                ui.label(deposit).classes("w-40 text-right")
        if row.split_blocked:
            ui.label(
                f"Cele instrumentów sumują się do {format_percent(row.instrument_targets_sum or 0)}, a nie do 100%: "
                "wpłata nie jest dzielona na instrumenty tej klasy."
            ).classes("text-sm text-warning").mark("instrument-split-blocked")
        if edit is not None and catalog:
            ui.button("Cele instrumentów", on_click=lambda: edit(asset_class, catalog)).props(
                "flat dense no-caps"
            ).mark(f"edit-instrument-targets-{asset_class.id}")


def _targets_dialog(
    asset_classes: Sequence[AssetClass], strategy: Strategy, on_save: Callable[[Strategy], None]
) -> None:
    """A target and a band field per Asset Class; an empty target leaves the class without one."""
    dialog = movable_dialog()
    dialog.on("hide", dialog.delete)
    fields: dict[int, tuple[ui.input, ui.input]] = {}
    with dialog, ui.card().classes("w-[560px]").mark("targets-dialog"):
        ui.label("Cele klas aktywów").classes("text-lg font-bold")
        ui.label("Udział klasy w wartości portfela i dopuszczalne odchylenie w punktach procentowych.").classes(
            "text-sm text-gray-500"
        )
        with ui.grid(columns="minmax(10rem, 2fr) 1fr 1fr").classes("w-full gap-x-4 gap-y-0 items-center"):
            for asset_class in asset_classes:
                target = strategy.class_targets.get(asset_class.id)
                ui.label(asset_class.name)
                percent = ui.input("Cel", value="" if target is None else format_exact(target.percent))
                percent.props('dense suffix="%"').mark(f"target-{asset_class.id}")
                band = ui.input("Pasmo ±", value=format_quantity(target.band if target else DEFAULT_BAND))
                band.props('dense suffix="pp"').mark(f"band-{asset_class.id}")
                fields[asset_class.id] = (percent, band)
        total = ui.label().classes("text-sm").mark("targets-total")
        error = ui.label().classes("text-negative").mark("targets-error")

        def typed() -> dict[int, ClassTarget]:
            targets = {}
            for class_id, (percent_field, band_field) in fields.items():
                percent = parse_optional_number(percent_field.value, "Cel")
                if percent is None:
                    continue
                band = parse_optional_number(band_field.value, "Pasmo tolerancji")
                targets[class_id] = ClassTarget(percent, DEFAULT_BAND if band is None else band)
            return targets

        def show_total() -> None:
            try:
                summed = sum((t.percent for t in typed().values()), Decimal(0))
            except InstrumentError, StrategyError:
                total.text = "Razem: —"
                return
            total.text = f"Razem: {format_percent(summed)}"
            total.classes(replace="text-sm" if summed in (0, 100) else "text-sm text-warning")

        def save() -> None:
            try:
                updated = replace(strategy, class_targets=typed())
            except (InstrumentError, StrategyError) as exc:
                error.text = str(exc)
                return
            dialog.close()
            on_save(updated)

        for percent_field, band_field in fields.values():
            percent_field.on_value_change(show_total)
            band_field.on_value_change(show_total)
        show_total()
        with ui.row().classes("w-full justify-end"):
            ui.button("Anuluj", on_click=dialog.close).props("flat")
            ui.button("Zapisz", on_click=save).mark("save-targets")
    dialog.open()


def _instrument_targets_dialog(
    asset_class: AssetClass,
    instruments: Sequence[Instrument],
    strategy: Strategy,
    on_save: Callable[[Strategy], None],
) -> None:
    """A field per Instrument of the class in the catalog, held or not: its percent of the class."""
    dialog = movable_dialog()
    dialog.on("hide", dialog.delete)
    fields: dict[int, ui.input] = {}
    with dialog, ui.card().classes("w-[480px]").mark("instrument-targets-dialog"):
        ui.label(f"Cele instrumentów: {asset_class.name}").classes("text-lg font-bold")
        ui.label("Udział instrumentu w klasie; razem 100%. Puste pole: bez celu.").classes("text-sm text-gray-500")
        for instrument in sorted(instruments, key=lambda i: i.name.casefold()):
            share = strategy.instrument_targets.get(instrument.id)
            field_ = ui.input(instrument.name, value="" if share is None else format_exact(share))
            field_.props('dense suffix="%"').classes("w-full").mark(f"instrument-target-{instrument.id}")
            fields[instrument.id] = field_
        total = ui.label().classes("text-sm").mark("instrument-targets-total")
        error = ui.label().classes("text-negative").mark("instrument-targets-error")

        def typed() -> dict[int, Decimal]:
            shares = {}
            for instrument_id, input_field in fields.items():
                share = parse_optional_number(input_field.value, f"Cel „{input_field.props['label']}”")
                if share is not None:
                    shares[instrument_id] = share
            return shares

        def show_total() -> None:
            try:
                summed = sum(typed().values(), Decimal(0))
            except InstrumentError:
                total.text = "Razem: —"
                return
            total.text = f"Razem: {format_percent(summed)}"
            total.classes(replace="text-sm" if summed in (0, 100) else "text-sm text-warning")

        def save() -> None:
            others = {i: p for i, p in strategy.instrument_targets.items() if i not in fields}
            try:
                updated = replace(strategy, instrument_targets=others | typed())
            except (InstrumentError, StrategyError) as exc:
                error.text = str(exc)
                return
            dialog.close()
            on_save(updated)

        for input_field in fields.values():
            input_field.on_value_change(show_total)
        show_total()
        with ui.row().classes("w-full justify-end"):
            ui.button("Anuluj", on_click=dialog.close).props("flat")
            ui.button("Zapisz", on_click=save).mark("save-instrument-targets")
    dialog.open()


def _difference(row: ClassRow) -> str:
    """The difference from the target in percentage points, e.g. "+10,00 pp"."""
    return format_points(row.difference or Decimal(0), signed=True)
