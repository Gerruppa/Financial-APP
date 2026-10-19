"""The Transakcje tab: the filtered, sortable list of Transactions (spec 3.3, L-27); the dialog for adding,
editing and deleting one is in ``ui/transaction_dialog.py``."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any

from nicegui import ui
from sqlalchemy import Engine

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
from financial_app.domain.recurring import RecurringDraft
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
from financial_app.domain.transactions import (
    Origin,
    Transaction,
    TransactionType,
)
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import list_transactions
from financial_app.sources.export import FileFormat, export_transactions
from financial_app.sources.nbp import NbpRates
from financial_app.ui.changes import Change
from financial_app.ui.recurring_drafts import prefill_of, recurring_drafts_list
from financial_app.ui.transaction_dialog import open_transaction_dialog
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
        with ui.column().classes("w-full max-w-screen-2xl gap-0").mark("transactions"):
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
            ui.label("Brak transakcji. Dodaj pierwszą przyciskiem „+”.").classes("k-muted")
            return
        account_names = {account.id: account.name for account in list_accounts(self.engine)}
        instruments = {instrument.id: instrument for instrument in list_instruments(self.engine)}
        names = {instrument_id: instrument.name for instrument_id, instrument in instruments.items()}
        transactions = view(listed, self.filters, self.sort, account_names, names)
        if not transactions:
            ui.label("Żadna transakcja nie spełnia filtrów.").classes("k-muted py-1").mark("no-match")
        for transaction in transactions:
            row = ui.element("div").classes("grid w-full gap-x-4 border-b py-1 cursor-pointer k-hover")
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
                            ui.label(f"{quantity} × {price}").classes("text-xs k-muted")
                            if transaction.withholding_tax:
                                fee, tax = format_pln(transaction.commission), format_pln(transaction.withholding_tax)
                                ui.label(f"opłata {fee} · podatek {tax}").classes("text-xs k-muted")
                        elif kind is TransactionType.SPLIT:
                            ui.label(f"split {transaction.split_ratio}").classes("text-xs k-muted")
                        elif kind is TransactionType.SECURITY_TRANSFER:
                            assert transaction.quantity is not None
                            ui.label(f"{format_quantity(transaction.quantity)} szt.").classes("text-xs k-muted")
                    if kind.is_dividend:
                        _dividend_cell(transaction)
                    if transaction.nbp_rate is not None:
                        ui.label(_rates_text(transaction)).classes("text-xs k-muted")
                with ui.column().classes("gap-0 items-end"):
                    if not kind.has_amount:
                        pass  # a Split or Security Transfer moves only units
                    elif kind is TransactionType.CASH_TRANSFER and transaction.is_paid_in_foreign_cash:  # #125
                        assert transaction.quantity is not None  # foreign cash, checked on creation
                        ui.label(format_amount(transaction.quantity, transaction.cash_currency))
                        ui.label(format_pln(transaction.actual_amount)).classes("text-xs k-muted")
                    elif kind is TransactionType.CASH_TRANSFER:
                        ui.label(format_pln(transaction.actual_amount))
                    elif kind is TransactionType.DRIP:
                        ui.label(f"reinwestowano {format_pln(transaction.actual_amount)}")
                        if transaction.tax_amount != transaction.actual_amount:
                            tax = format_pln(transaction.tax_amount)
                            ui.label(f"podatkowa {tax}").classes("text-xs k-muted")
                    elif transaction.is_paid_in_foreign_cash:
                        currency = transaction.cash_currency
                        ui.label(format_amount(transaction.foreign_cash_change, currency, signed=True))
                        actual = format_pln(transaction.actual_cash_change, signed=True)
                        ui.label(f"rzeczywista {actual}").classes("text-xs k-muted")
                    else:
                        ui.label(format_pln(transaction.cash_change, signed=True))
                    if kind is not TransactionType.DRIP and transaction.tax_amount != transaction.actual_amount:
                        tax = format_pln(transaction.tax_cash_change, signed=True)
                        ui.label(f"podatkowa {tax}").classes("text-xs k-muted")
                with ui.column().classes("gap-0"):
                    ui.label(transaction.comment).classes("k-muted")
                    if transaction.origin is not Origin.MANUAL:
                        ui.label(transaction.origin.label).classes("text-xs k-muted").mark("transaction-origin")


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
    ui.label(f"{amount} po {rate}").classes("text-xs k-muted")


def _dividend_cell(payout: Transaction) -> None:
    """A Dividend's gross amount and withholding tax; a DRIP's units bought with it."""
    currency = payout.dividend_currency
    if payout.quantity is not None:
        ui.label(f"+{format_quantity(payout.quantity)} szt.").classes("text-xs k-muted")
    assert payout.gross is not None
    gross, tax = format_amount(payout.gross, currency), format_amount(payout.withholding_tax, currency)
    ui.label(f"brutto {gross} · podatek {tax}").classes("text-xs k-muted")


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
