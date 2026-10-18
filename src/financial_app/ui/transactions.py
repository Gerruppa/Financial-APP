"""The Transakcje tab and the transaction dialog for adding, editing and deleting (spec 3.3).

The dialog binds its widgets to the form model in ``domain/transaction_form.py`` (#111), which holds what each
Transaction Type shows and how its fields read, and saves through ``sources/transaction_saving.py`` (#110).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.bonds import BondType
from financial_app.domain.currencies import MissingNbpRateError
from financial_app.domain.formatting import (
    format_amount,
    format_date,
    format_exact,
    format_pln,
    format_quantity,
    format_rate,
    format_unit_price,
    parse_date,
    parse_number,
)
from financial_app.domain.instruments import InstrumentError
from financial_app.domain.recurring import RecurringDraft, repeating
from financial_app.domain.transaction_filters import (
    CHOICE_COLUMNS,
    NEWEST_FIRST,
    NO_FILTER,
    Column,
    Sort,
    TransactionFilter,
    account_options,
    instrument_options,
    type_options,
    view,
)
from financial_app.domain.transaction_form import (
    BOND_TYPE_OPTIONS,
    BUY_CURRENCY,
    SELL_CURRENCY,
    TRANSACTION_TYPE_OPTIONS,
    FormContext,
    FormLayout,
    FormPrefill,
    FormState,
    FormTexts,
    TransactionForm,
)
from financial_app.domain.transactions import (
    Origin,
    Transaction,
    TransactionDraft,
    TransactionError,
    TransactionType,
)
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.bond_data import load_series_terms
from financial_app.persistence.bond_series import list_bond_series, load_bond_data
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import list_transactions, transactions_in_entry_order
from financial_app.sources.export import FileFormat, export_transactions
from financial_app.sources.nbp import NbpRates
from financial_app.sources.transaction_saving import delete_saved, save_transaction
from financial_app.ui.changes import Change
from financial_app.ui.dialogs import movable_dialog
from financial_app.ui.multi_asset import open_split_dialog
from financial_app.ui.recurring_drafts import prefill_of, recurring_drafts_list
from financial_app.ui.recurring_rules import open_rule_dialog
from financial_app.ui.save_warnings import show_warnings
from financial_app.ui.view_scope import ViewScope, breadcrumbs

COLUMNS = "grid-template-columns: 7rem minmax(8rem, 1fr) 6rem minmax(9rem, 1fr) 9rem minmax(8rem, 2fr)"


HEADERS = {
    Column.DATE: "Data",
    Column.ACCOUNT: "Konto",
    Column.TYPE: "Typ",
    Column.INSTRUMENT: "Instrument",
    Column.AMOUNT: "Kwota",
    Column.COMMENT: "Komentarz",
}
# A newly chosen column sorts this way first: dates and amounts largest first, text from A
_FIRST_DESCENDING = {Column.DATE, Column.AMOUNT}
NO_INSTRUMENT_LABEL = "(bez instrumentu)"


@dataclass
class TransactionsPage:
    """The Transakcje tab; clicking a Transaction opens it for editing or deleting. In an Account's View Scope it lists
    only that Account's Transactions, Cash and Security Transfers to it included. Each column header sorts the list and
    filters it (L-27); the export buttons export what is listed. Above it, the Recurring Rules' Drafts of the
    View Scope wait to be confirmed (issue #97). ``publish`` tells the window what a save here changed."""

    # The changes it redraws on (ui/changes.py)
    CHANGES = frozenset({Change.TRANSACTIONS, Change.SCOPE, Change.RECURRING_RULES})

    engine: Engine
    rates: NbpRates
    scope: ViewScope
    publish: Callable[..., None]
    filters: TransactionFilter = NO_FILTER
    sort: Sort = NEWEST_FIRST
    _headers: dict[Column, _ColumnHeader] = field(init=False, default_factory=dict)
    _header_row: ui.element = field(init=False)

    def refresh(self) -> None:
        """Redraw the list if it is on screen (e.g. after a save)."""
        self.recurring.refresh()
        self.notes.refresh()
        self.rows.refresh()

    def build(self) -> None:
        ui.label("Transakcje").classes("text-2xl font-bold")
        with ui.row().classes("gap-2"):
            ui.button("Eksportuj CSV", on_click=lambda: self.export("csv")).props("outline")
            ui.button("Eksportuj XLSX", on_click=lambda: self.export("xlsx")).props("outline")
        self.recurring()
        # The marker sits outside the refreshable list so it survives a refresh
        with ui.column().classes("w-full max-w-6xl gap-0").mark("transactions"):
            self.notes()
            # The headers stay while the list redraws, so an open filter stays open as it is typed in
            self._header_row = ui.element("div").classes("grid w-full gap-x-4 border-b py-1 font-medium").style(COLUMNS)
            with self._header_row:
                self._headers = {column: _ColumnHeader(self, column) for column in Column}
            self.rows()

    def export(self, file_format: FileFormat) -> None:
        """Hands the listed Transactions (those of the View Scope the filters keep) to the browser as a file, in the
        list's order."""
        name, data = export_transactions(self.engine, file_format, self.scope.account_id, self.filters, self.sort)
        ui.download(data, name)

    def scoped(self) -> list[Transaction]:
        return [t for t in list_transactions(self.engine) if self.scope.includes(t)]

    def sort_by(self, column: Column) -> None:
        """The column's header clicked: the same column turns its order round, another sorts by it."""
        if self.sort.column is column:
            self.sort = Sort(column, not self.sort.descending)
        else:
            self.sort = Sort(column, column in _FIRST_DESCENDING)
        self.filters_changed()

    def filter_by(self, filters: TransactionFilter) -> None:
        self.filters = filters
        self.filters_changed()

    def clear_filters(self) -> None:
        self.filter_by(NO_FILTER)
        for header in self._headers.values():
            header.menu.close()

    def filters_changed(self) -> None:
        for header in self._headers.values():
            header.show()
        self.refresh()

    @ui.refreshable_method
    def recurring(self) -> None:
        recurring_drafts_list(
            self.engine,
            self.rates,
            self.scope.account_id,
            self.edit_draft,
            on_saved=self.saved,
            on_skipped=lambda: self.publish(Change.RECURRING_RULES),
        )

    def saved(self) -> None:
        self.publish(Change.TRANSACTIONS)

    def edit_draft(self, draft: RecurringDraft) -> None:
        """Open a Recurring Rule's Draft in the transaction dialog; what it saves covers the Draft's occurrence."""
        open_transaction_dialog(self.engine, self.rates, self.saved, start_with=prefill_of(draft), link=draft.link)

    def open(self, transaction: Transaction) -> None:
        open_transaction_dialog(
            self.engine,
            self.rates,
            self.saved,
            transaction,
            on_rules_changed=lambda: self.publish(Change.RECURRING_RULES),
        )

    @ui.refreshable_method
    def notes(self) -> None:
        breadcrumbs(self.scope)
        if self.filters.active:
            ui.button("wyczyść filtry", icon="filter_alt_off", on_click=self.clear_filters).props(
                "flat dense no-caps size=sm"
            ).classes("self-start").mark("clear-filters")

    @ui.refreshable_method
    def rows(self) -> None:
        listed = self.scoped()
        self._header_row.set_visibility(bool(listed))
        if not listed:
            ui.label("Brak transakcji. Dodaj pierwszą przyciskiem „+”.").classes("text-gray-500")
            return
        account_names = {account.id: account.name for account in list_accounts(self.engine)}
        instruments = {instrument.id: instrument for instrument in list_instruments(self.engine)}
        names = {instrument_id: instrument.name for instrument_id, instrument in instruments.items()}
        transactions = view(listed, self.filters, self.sort, account_names, names)
        if not transactions:
            ui.label("Żadna transakcja nie spełnia filtrów.").classes("text-gray-500 py-1").mark("no-match")
        for transaction in transactions:
            row = ui.element("div").classes("grid w-full gap-x-4 border-b py-1 cursor-pointer hover:bg-gray-100")
            row.style(COLUMNS).mark("transaction-row")
            row.on("click", lambda t=transaction: self.open(t))
            with row:
                ui.label(format_date(transaction.date))
                target = transaction.target_account_id
                source = account_names[transaction.account_id]
                ui.label(source if target is None else f"{source} → {account_names[target]}")
                ui.label(transaction.transaction_type.label)
                with ui.column().classes("gap-0"):
                    kind = transaction.transaction_type
                    if kind is TransactionType.CURRENCY_EXCHANGE:
                        _exchange_cell(transaction)
                    if transaction.instrument_id is not None:
                        instrument = instruments[transaction.instrument_id]
                        ui.label(instrument.name)
                        if kind.is_buy_or_sell:
                            assert transaction.quantity is not None and transaction.price is not None
                            price = format_unit_price(transaction.price, instrument.quote_currency)
                            quantity = format_quantity(transaction.quantity)
                            ui.label(f"{quantity} × {price}").classes("text-xs text-gray-500")
                            if transaction.withholding_tax:
                                fee, tax = format_pln(transaction.commission), format_pln(transaction.withholding_tax)
                                ui.label(f"opłata {fee} · podatek {tax}").classes("text-xs text-gray-500")
                        elif kind is TransactionType.SPLIT:
                            ui.label(f"split {transaction.split_ratio}").classes("text-xs text-gray-500")
                        elif kind is TransactionType.SECURITY_TRANSFER:
                            assert transaction.quantity is not None
                            ui.label(f"{format_quantity(transaction.quantity)} szt.").classes("text-xs text-gray-500")
                    if kind.is_dividend:
                        _dividend_cell(transaction)
                    if transaction.nbp_rate is not None:
                        ui.label(_rates_text(transaction)).classes("text-xs text-gray-500")
                with ui.column().classes("gap-0 items-end"):
                    if not kind.has_amount:
                        pass  # a Split or Security Transfer moves only units
                    elif kind is TransactionType.CASH_TRANSFER:
                        ui.label(format_pln(transaction.actual_amount))
                    elif kind is TransactionType.DRIP:
                        ui.label(f"reinwestowano {format_pln(transaction.actual_amount)}")
                        if transaction.tax_amount != transaction.actual_amount:
                            tax = format_pln(transaction.tax_amount)
                            ui.label(f"podatkowa {tax}").classes("text-xs text-gray-500")
                    elif transaction.is_paid_in_foreign_cash:
                        currency = transaction.cash_currency
                        ui.label(format_amount(transaction.foreign_cash_change, currency, signed=True))
                        actual = format_pln(transaction.actual_cash_change, signed=True)
                        ui.label(f"rzeczywista {actual}").classes("text-xs text-gray-500")
                    else:
                        ui.label(format_pln(transaction.cash_change, signed=True))
                    if kind is not TransactionType.DRIP and transaction.tax_amount != transaction.actual_amount:
                        tax = format_pln(transaction.tax_cash_change, signed=True)
                        ui.label(f"podatkowa {tax}").classes("text-xs text-gray-500")
                with ui.column().classes("gap-0"):
                    ui.label(transaction.comment).classes("text-gray-600")
                    if transaction.origin is not Origin.MANUAL:
                        ui.label(transaction.origin.label).classes("text-xs text-gray-500").mark("transaction-origin")


class _ColumnHeader:
    """A column's header: its name sorts the list by it (the arrow shows the order), the funnel opens its filter,
    coloured while the filter is set. The menu is drawn only while open, so it offers the values listed then."""

    menu: ui.menu

    def __init__(self, page: TransactionsPage, column: Column) -> None:
        self.page = page
        self.column = column
        with ui.row().classes("items-center gap-0 no-wrap"):
            self.sort_button = ui.button(HEADERS[column], on_click=lambda: page.sort_by(column))
            self.sort_button.props("flat dense no-caps").classes("font-medium").mark(f"sort-{column}")
            self.filter_button = ui.button(icon="filter_alt", on_click=lambda: self.menu.open()).props(
                "flat dense round size=sm"
            )
            with self.filter_button:
                self.menu = ui.menu()
                self.menu.on_value_change(lambda _: self.content.refresh())
                with self.menu:
                    self.content()
        self.show()

    def show(self) -> None:
        sort = self.page.sort
        arrow = ("arrow_downward" if sort.descending else "arrow_upward") if sort.column is self.column else None
        if arrow:
            self.sort_button.props(f"icon-right={arrow}")
        else:
            self.sort_button.props(remove="icon-right")
        active = self.page.filters.is_set(self.column)
        self.filter_button.props(f"color={'primary' if active else 'grey'}")
        self.filter_button.mark(f"filter-{self.column}", *(["filter-active"] if active else []))

    @ui.refreshable_method
    def content(self) -> None:
        if not self.menu.value:
            return
        with ui.column().classes("gap-1 p-3 min-w-56"):
            if self.column in CHOICE_COLUMNS:
                self._choices()
            elif self.column is Column.COMMENT:
                field_input = ui.input("Zawiera", value=self.page.filters.comment).props("dense clearable autofocus")
                field_input.on_value_change(
                    lambda e: self.page.filter_by(replace(self.page.filters, comment=e.value or ""))
                )
                field_input.mark("filter-comment-text")
            else:
                self._range()

    def _options(self) -> Sequence[tuple[object, str]]:
        page = self.page
        listed = page.scoped()
        if self.column is Column.ACCOUNT:
            names = {account.id: account.name for account in list_accounts(page.engine)}
            return account_options(listed, names)
        if self.column is Column.TYPE:
            return type_options(listed)
        names = {instrument.id: instrument.name for instrument in list_instruments(page.engine)}
        return [(i, name or NO_INSTRUMENT_LABEL) for i, name in instrument_options(listed, names)]

    def _choices(self) -> None:
        """A checkbox per value listed, all ticked while the column is unfiltered."""
        options = self._options()
        present = {key for key, _ in options}
        chosen = self.page.filters.chosen(self.column)

        def choose(value: frozenset[object] | None) -> None:
            self.page.filter_by(self.page.filters.choose(self.column, value))
            self.content.refresh()

        def toggle(key: object, ticked: bool) -> None:
            current = present if chosen is None else set(chosen)
            kept = current | {key} if ticked else current - {key}
            choose(None if present <= kept else frozenset(kept))

        ui.checkbox("(zaznacz wszystkie)", value=chosen is None).on_value_change(
            lambda e: choose(None if e.value else frozenset())
        ).mark(f"filter-all-{self.column}")
        for key, label in options:
            ui.checkbox(label, value=chosen is None or key in chosen).on_value_change(
                lambda e, key=key: toggle(key, e.value)
            ).mark(f"filter-option-{self.column}-{key}")

    def _range(self) -> None:
        """ "od" and "do", either may stay empty; a value that cannot be read leaves the filter as it was."""
        amount = self.column is Column.AMOUNT
        parse: Callable[[str], Decimal | date] = parse_number if amount else parse_date
        show: Callable[[Any], str] = format_exact if amount else format_date
        hint = "kwota rzeczywista" if amount else "dd.mm.rrrr"
        for last, (label, value) in enumerate(zip(("od", "do"), self.page.filters.bounds(self.column), strict=True)):
            end_input = ui.input(label, value="" if value is None else show(value))
            end_input.props(f"dense clearable hint='{hint}'")
            end_input.on_value_change(
                lambda _, last=bool(last), end_input=end_input: self._set_end(last, end_input, parse)
            )
            end_input.mark(f"filter-{self.column}-{label}")

    def _set_end(self, last: bool, end_input: ui.input, parse: Callable[[str], Decimal | date]) -> None:
        text = (end_input.value or "").strip()
        try:
            value = parse(text) if text else None
        except ValueError:
            end_input.props("error error-message='Nieprawidłowa wartość'")
            return
        end_input.props(remove="error error-message")
        self.page.filter_by(self.page.filters.bound(self.column, last, value))


def _exchange_cell(exchange: Transaction) -> None:
    """Which way the currency went, how much and at what rate (PLN per unit)."""
    currency = exchange.cash_currency
    ui.label(f"{currency} → PLN" if exchange.to_pln else f"PLN → {currency}")
    assert exchange.quantity is not None
    rate = format_rate(exchange.actual_amount / exchange.quantity)
    amount = format_amount(exchange.foreign_cash_change, currency, signed=True)
    ui.label(f"{amount} po {rate}").classes("text-xs text-gray-500")


def _dividend_cell(payout: Transaction) -> None:
    """A Dividend's gross amount and withholding tax; a DRIP's units bought with it."""
    currency = payout.dividend_currency
    if payout.quantity is not None:
        ui.label(f"+{format_quantity(payout.quantity)} szt.").classes("text-xs text-gray-500")
    assert payout.gross is not None
    gross, tax = format_amount(payout.gross, currency), format_amount(payout.withholding_tax, currency)
    ui.label(f"brutto {gross} · podatek {tax}").classes("text-xs text-gray-500")


def open_transaction_dialog(
    engine: Engine,
    rates: NbpRates,
    on_saved: Callable[[], None],
    transaction: Transaction | None = None,
    *,
    start_with: FormPrefill | None = None,
    link: Callable[[TransactionDraft], TransactionDraft] | None = None,
    on_rules_changed: Callable[[], None] | None = None,
) -> None:
    """Open a fresh dialog for a new Transaction (``None``), filled with ``start_with`` if given, or for editing or
    deleting ``transaction``.

    It is built on demand and removed when closed; ``on_saved`` runs after a save or a delete. ``link`` turns what it
    saves into the Transaction covering a Recurring Rule's occurrence (issue #97). With ``on_rules_changed`` an edited
    Deposit or Buy offers "Powtarzaj…", a new Recurring Rule repeating it, and ``on_rules_changed`` runs once it is
    saved. Its rules live in ``domain/transaction_form.py``; the dialog only binds its widgets to them.
    """
    dialog = movable_dialog()
    dialog.on("hide", dialog.delete)
    form = TransactionForm(
        FormContext(
            accounts=list_accounts(engine),
            instruments=list_instruments(engine),
            transactions=transactions_in_entry_order(engine),
            held_series={series.name: series for series in list_bond_series(engine).values()},
            mf_terms=load_series_terms(engine),
            bond_data=load_bond_data(engine),
            rates=rates.before,
            edited=transaction,
        )
    )
    with dialog, ui.card().classes("w-[460px]"):
        ui.label("Nowa transakcja" if transaction is None else "Edytuj transakcję").classes("text-lg font-bold")
        if not form.accounts:
            ui.label("Najpierw dodaj konto z walutą PLN w zakładce Ustawienia.").classes("text-gray-500")
            with ui.row().classes("w-full justify-end"):
                ui.button("Zamknij", on_click=dialog.close).props("flat")
            dialog.open()
            return

        start = form.initial_state(date.today(), start_with)
        texts = start.texts
        # The Account comes first and stands out (#118): it decides the type's fields, Cash currencies and bond mode
        account = ui.select(form.accounts, label="Konto", value=start.account_id).props("filled bg-color=blue-1")
        account.classes("w-full [&_.q-field\\_\\_native]:font-bold").mark("transaction-account")
        transaction_type = ui.select(TRANSACTION_TYPE_OPTIONS, label="Typ", value=start.kind.value)
        transaction_type.classes("w-full").mark("transaction-type")
        target = ui.select(form.targets, label="Na konto", value=start.target_id).classes("w-full")
        target.mark("transaction-target-account")
        day = ui.input("Data", value=start.day).classes("w-full").mark("transaction-date")
        with day.add_slot("append"):
            icon = ui.icon("event").classes("cursor-pointer")
            with ui.menu() as menu:
                ui.date(mask="DD.MM.YYYY").bind_value(day).on_value_change(menu.close)
            icon.on("click", menu.open)

        with ui.column().classes("w-full gap-0") as exchange_fields:
            directions = {BUY_CURRENCY: "PLN → waluta", SELL_CURRENCY: "waluta → PLN"}
            direction = ui.select(directions, label="Kierunek", value=start.direction).classes("w-full")
            direction.mark("transaction-direction")
            exchange_currency = ui.select([], label="Waluta").classes("w-full").mark("transaction-currency")
            foreign_amount = ui.input(value=texts.foreign_amount).classes("w-full")
            foreign_amount.mark("transaction-foreign-amount")
        cash_currency = ui.select([start.cash_currency], label="Waluta", value=start.cash_currency).classes("w-full")
        cash_currency.mark("transaction-cash-currency")
        amount = ui.input("Kwota (zł)", value=texts.amount).classes("w-full").mark("transaction-amount")
        with ui.column().classes("w-full gap-0") as instrument_fields:
            bond_mode = ui.checkbox("Obligacje skarbowe detaliczne", value=start.bond_mode)
            bond_mode.mark("transaction-bond-mode")
            bond_type = ui.select(BOND_TYPE_OPTIONS, label="Rodzaj obligacji", value=start.bond_type.value)
            bond_type.classes("w-full").mark("transaction-bond-type")
            # Any Series of the type may be picked, e.g. for an older purchase (L-26); the date's own is the default
            series_choice = ui.select({}, label="Seria", with_input=True).classes("w-full")
            series_choice.mark("transaction-bond-series-choice")
            series_text = ui.label().classes("text-sm text-gray-600").mark("transaction-bond-series")
            rollover = ui.checkbox("z rolowania", value=start.rollover).mark("transaction-rollover")
            # A Dividend without an Instrument is interest, e.g. on the Account's cash
            instrument = ui.select(form.instruments, label="Instrument", value=start.instrument_id, clearable=True)
            instrument.classes("w-full").mark("transaction-instrument")
            # An Early Redemption names the Lot it redeems (ADR-0007)
            lot = ui.select({}, label="Partia").classes("w-full").mark("transaction-lot")
            if not form.instruments:
                ui.label("Najpierw dodaj instrument w zakładce Ustawienia.").classes("text-gray-500")
            own_dividend_currency = start.dividend_currency
            dividend_currency = ui.select(
                [own_dividend_currency] if own_dividend_currency else [], label="Waluta", value=own_dividend_currency
            )
            dividend_currency.classes("w-full")
            dividend_currency.mark("transaction-dividend-currency")
            # A Buy's amount to spend proposes the quantity (#120); it is not saved
            spend = ui.input(value=texts.spend).classes("w-full").mark("transaction-spend")
            spend.props('hint="Proponuje liczbę; nie jest zapisywana"')
            quantity = ui.input("Liczba", value=texts.quantity).classes("w-full").mark("transaction-quantity")
            ratio = ui.input("Split (X:Y)", value=texts.ratio).classes("w-full").mark("transaction-split-ratio")
            ratio.props('hint="X nowych jednostek za każde Y dotychczasowych, np. 2:1"')
            price = ui.input("Cena (zł)", value=texts.price).classes("w-full").mark("transaction-price")
            gross = ui.input(value=texts.gross).classes("w-full").mark("transaction-gross")
            withholding_tax = ui.input(value=texts.withholding_tax).classes("w-full")
            withholding_tax.mark("transaction-withholding-tax")
            net = ui.label().classes("text-sm text-gray-600").mark("transaction-net")
        # How it is paid; outside the Instrument fields, as a foreign Deposit or Withdrawal takes a rate too
        paid_from = ui.select({}, label="Płatność").classes("w-full").mark("transaction-paid-from")
        fx_rate = ui.input(value=texts.fx_rate)
        fx_rate.classes("w-full").mark("transaction-fx-rate")
        commission = ui.input("Prowizja (zł)", value=texts.commission).classes("w-full")
        commission.mark("transaction-commission")
        convert = ui.checkbox(value=start.convert).mark("transaction-conversion")
        charged = ui.input("Kwota pobrana przez brokera (zł)", value=texts.charged).classes("w-full")
        charged.props('hint="Za liczbę × cenę, bez prowizji"').mark("transaction-charged")
        auto_exchange = ui.checkbox("Wymień walutę automatycznie").mark("transaction-auto-exchange")
        comment = ui.input("Komentarz", value=texts.comment).classes("w-full").mark("transaction-comment")
        error = ui.label().classes("text-negative").mark("transaction-error")

        picked: list[str | None] = [None]  # a Series the user picked instead of the one the date gives
        offered: list[tuple[list[str], str | None] | None] = [None]  # the Series list and value shown last
        syncing = [False]  # set while the dialog itself fills the Series list
        # Set while a layout is applied, and set again when a value it sets asks for another one
        applying, again = [False], [False]

        def state() -> FormState:
            return FormState(
                account_id=account.value,
                kind=TransactionType(transaction_type.value),
                day=day.value or "",
                texts=FormTexts(
                    amount=amount.value or "",
                    foreign_amount=foreign_amount.value or "",
                    quantity=quantity.value or "",
                    price=price.value or "",
                    fx_rate=fx_rate.value or "",
                    commission=commission.value or "",
                    charged=charged.value or "",
                    gross=gross.value or "",
                    withholding_tax=withholding_tax.value or "",
                    ratio=ratio.value or "",
                    comment=comment.value or "",
                    spend=spend.value or "",
                ),
                target_id=target.value,
                instrument_id=instrument.value,
                bond_mode=bool(bond_mode.value),
                bond_type=BondType(bond_type.value),
                series_pick=picked[0],
                rollover=bool(rollover.value),
                lot_id=lot.value,
                direction=direction.value,
                exchange_currency=exchange_currency.value,
                cash_currency=cash_currency.value,
                dividend_currency=dividend_currency.value,
                paid_from=paid_from.value,
                convert=bool(convert.value),
                auto_exchange=bool(auto_exchange.value),
            )

        def update() -> None:
            """Show the fields the form's state needs; a value it sets that changes the state runs it once more."""
            if applying[0]:
                again[0] = True
                return
            applying[0] = True
            try:
                for _ in range(5):  # settles in one or two rounds
                    again[0] = False
                    apply(form.layout(state()))
                    if not again[0]:
                        break
            finally:
                applying[0] = False

        def apply(layout: FormLayout) -> None:
            amount.visible = layout.amount.visible
            amount.props(f'label="{layout.amount.label}"')
            instrument_fields.visible = layout.instrument_fields
            target.visible = layout.target.visible
            target.set_options(dict(layout.target.options), value=layout.target.value)
            ratio.visible = layout.ratio
            exchange_fields.visible = layout.exchange_fields
            dividend_currency.visible = layout.dividend_currency.visible
            if layout.dividend_currency.visible:
                currencies = list(layout.dividend_currency.options)
                dividend_currency.set_options(currencies, value=layout.dividend_currency.value)
            spend.visible = layout.spend.visible
            spend.props(f'label="{layout.spend.label}"')
            quantity.visible = layout.quantity.visible
            quantity.props(f'label="{layout.quantity.label}"')
            bond_mode.visible = layout.bond_mode
            for bond_field in (bond_type, series_choice, series_text):
                bond_field.visible = layout.bond_fields
            instrument.visible = layout.instrument
            price.visible = layout.price.visible
            price.props(f'label="{layout.price.label}"')
            commission.visible = layout.commission
            rollover.visible = layout.rollover
            if layout.bond_fields:
                list_series(layout.series.options, layout.series.value)
            series_text.text = layout.series_text
            lot.visible = layout.lot.visible
            if layout.lot.visible:
                lot.set_options(dict(layout.lot.options), value=layout.lot.value)
            gross.visible = layout.gross.visible
            gross.props(f'label="{layout.gross.label}"')
            withholding_tax.visible = layout.withholding_tax.visible
            withholding_tax.props(f'label="{layout.withholding_tax.label}"')
            net.visible = layout.net.visible
            prefill_redemption()
            propose_quantity()
            show_net()
            fx_rate.visible = layout.fx_rate.visible
            fx_rate.props(f'label="{layout.fx_rate.label}" hint="{layout.fx_rate.hint}"')
            paid_from.visible = layout.paid_from.visible
            paid_from.props(f'label="{layout.paid_from.label}"')
            if layout.paid_from.visible:
                paid_from.set_options(dict(layout.paid_from.options), value=layout.paid_from.value)
            convert.visible = layout.convert.visible
            if layout.convert.label:
                convert.text = layout.convert.label
            charged.visible = layout.charged.visible
            charged.props(f'label="{layout.charged.label}" hint="{layout.charged.hint}"')
            cash_currency.visible = layout.cash_currency.visible
            cash_currency.set_options(list(layout.cash_currency.options), value=layout.cash_currency.value)
            auto_exchange.visible = layout.auto_exchange
            exchange_currency.set_options(list(layout.exchange_currency.options), value=layout.exchange_currency.value)
            direction.set_options(dict(layout.direction.options), value=layout.direction.value)
            foreign_amount.props(f'label="{layout.foreign_amount.label}"')

        def list_series(options: Mapping[str, str], value: str | None) -> None:
            """Offer the type's Series, sending the list only when it changed."""
            if (list(options), value) == offered[0]:
                return  # nothing to send again
            offered[0] = (list(options), value)
            syncing[0] = True
            try:
                series_choice.set_options(dict(options), value=value)
            finally:
                syncing[0] = False

        def series_picked() -> None:
            if syncing[0]:
                return
            value = series_choice.value
            picked[0] = None if value is None or value == form.date_series(state()) else str(value)
            update()
            bond_price()

        def type_changed() -> None:
            picked[0] = None  # a Series of another type is not one of this type

        def show_net() -> None:
            net.text = form.net_text(state())

        set_price = [""]  # the price the bond mode set last, which it may set again
        # What the Early Redemption prefill set last in each field, which it may set again; a value the user typed (or
        # the edited Sell's own) stays
        prefilled: dict[ui.input, str] = {}
        prefilling = [False]

        def prefill(field: ui.input, value: str) -> None:
            if not field.value.strip() or field.value == prefilled.get(field):
                prefilled[field] = value
                field.value = value

        def prefill_redemption() -> None:
            """Fill an Early Redemption with the chosen Lot's bonds, one bond's gross value as the price, the fee as
            the commission and the tax the Account's Tax Regime withholds (spec 3.4.1)."""
            if prefilling[0] or not form.redeems_bonds(state()):
                return
            prefilling[0] = True
            try:
                units = form.lot_quantity(state())
                if units is None:
                    return
                prefill(quantity, units)
                redemption = form.redemption(state())
                if redemption is None:
                    return
                prefill(price, format_exact(redemption.price))
                prefill(commission, format_exact(redemption.fee))
                prefill(withholding_tax, format_exact(redemption.tax))
            finally:
                prefilling[0] = False

        def propose_quantity() -> None:
            """Fill the quantity the amount to spend buys, until the user types a quantity of their own (#120)."""
            proposal = form.proposed_quantity(state())
            if proposal is not None:
                prefill(quantity, proposal)

        def bond_price(rollover_changed: bool = False) -> None:
            """Price the bond mode's purchase: 100 zł, or the Rollover price of the Series. A price the user typed (or
            the edited Buy's own) stays unless the Rollover is switched."""
            value = form.bond_price(state())
            if value is None:
                return
            if not rollover_changed and price.value.strip() and price.value != set_price[0]:
                return
            price.value = set_price[0] = value

        def account_changed() -> None:
            # A new Buy follows the Account: the bond mode on a Bonds Account, else an Instrument
            if transaction is None:
                bond_mode.value = form.bond_mode_for(account.value)

        update()
        if transaction is None:
            bond_price()
        account.on_value_change(account_changed)
        rollover.on_value_change(lambda: bond_price(rollover_changed=True))
        rollover.on_value_change(update)
        series_choice.on_value_change(series_picked)
        bond_type.on_value_change(type_changed)  # before the handlers that read the chosen Series
        for bond_field in (bond_mode, bond_type, day, transaction_type):
            bond_field.on_value_change(lambda: bond_price())
        for field in (
            transaction_type,
            account,
            instrument,
            direction,
            exchange_currency,
            cash_currency,
            dividend_currency,
            paid_from,
            convert,
            bond_mode,
            bond_type,
            day,
        ):
            field.on_value_change(update)
        for redemption_input in (lot, quantity):
            redemption_input.on_value_change(prefill_redemption)
        for net_input in (gross, withholding_tax, quantity, price, commission):
            net_input.on_value_change(show_net)
        for proposal_input in (spend, price, commission, fx_rate):
            proposal_input.on_value_change(propose_quantity)

        def save() -> None:
            form_state = state()
            try:
                saved = save_transaction(
                    engine,
                    lambda series_id: (link or _unlinked)(form.draft(form_state, series_id)),
                    edited=transaction,
                    series=form.series_to_buy(form_state),
                    with_exchange=form.with_exchange(form_state),
                )
            except (TransactionError, MissingNbpRateError, InstrumentError) as exc:
                error.text = str(exc)
                return
            dialog.close()
            # The dialog asks for a Multi-asset Split itself, so it is no warning here
            show_warnings(saved.warnings, unsplit=False)
            on_saved()
            for unsplit in saved.warnings.unsplit:
                open_split_dialog(engine, unsplit, on_saved)

        def delete(confirmation: ui.dialog) -> None:
            assert transaction is not None
            confirmation.close()
            try:
                deleted = delete_saved(engine, transaction.id)
            except TransactionError as exc:
                error.text = f"Nie można usunąć tej transakcji. {exc}"
                return
            dialog.close()
            show_warnings(deleted.warnings, "Usunięto")
            on_saved()

        with ui.row().classes("w-full items-center"):
            if transaction is not None:
                delete_button = ui.button("Usuń", on_click=lambda: _confirm_delete(delete))
                delete_button.props("flat color=negative").mark("delete-transaction")
            repeatable = (TransactionType.DEPOSIT, TransactionType.BUY)
            if transaction is not None and on_rules_changed is not None and transaction.transaction_type in repeatable:

                def repeat() -> None:
                    assert transaction is not None and on_rules_changed is not None
                    dialog.close()
                    open_rule_dialog(engine, rates.today(), on_rules_changed, defaults=repeating(transaction))

                ui.button("Powtarzaj…", on_click=repeat).props("flat no-caps").mark("repeat-transaction").tooltip(
                    "Nowa reguła cykliczna na wzór tej transakcji"
                )
            ui.space()
            ui.button("Anuluj", on_click=dialog.close).props("flat")
            ui.button("Zapisz" if transaction is None else "Zapisz zmiany", on_click=save)
    dialog.open()


def _unlinked(draft: TransactionDraft) -> TransactionDraft:
    return draft


def _confirm_delete(delete: Callable[[ui.dialog], None]) -> None:
    """Ask before deleting; ``delete`` gets the confirmation dialog so that it can close it."""
    confirmation = ui.dialog()
    confirmation.on("hide", confirmation.delete)
    with confirmation, ui.card():
        ui.label("Usunąć tę transakcję?").classes("text-lg font-bold")
        ui.label("Partie i salda zostaną przeliczone bez niej.").classes("text-gray-600")
        with ui.row().classes("w-full justify-end"):
            ui.button("Anuluj", on_click=confirmation.close).props("flat").mark("cancel-delete")
            ui.button("Usuń", on_click=lambda: delete(confirmation)).props("color=negative").mark("confirm-delete")
    confirmation.open()


def _rates_text(trade: Transaction) -> str:
    """The rate the trade was converted at, if not the NBP Rate, then the NBP Rate with its table and publication day.

    A broker-converted trade shows its effective rate and FX Conversion Fee.
    """
    nbp_rate = trade.nbp_rate
    assert nbp_rate is not None
    nbp = f"NBP {format_exact(nbp_rate.rate)} ({nbp_rate.table} z {format_date(nbp_rate.published_on)})"
    fee = trade.fx_conversion_fee
    if fee is not None:
        return f"kurs {format_rate(trade.effective_fx_rate)} · przewalutowanie {format_pln(fee)} · {nbp}"
    return nbp if trade.fx_rate is None else f"kurs {format_exact(trade.fx_rate)} · {nbp}"
