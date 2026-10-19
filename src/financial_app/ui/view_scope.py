"""The View Scope switcher in the header and the breadcrumbs back to Total (spec section 5 and 6.1).

The switcher offers Total first, then the active Accounts by value descending, each with its value, share-of-total bar
and daily change ("—" while History loads); inactive Accounts wait behind "pokaż nieaktywne". The scope is remembered
in ``app_settings``, and the tabs following it redraw through ``ViewScope.on_change``.
"""

from collections.abc import Callable
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_pln
from financial_app.domain.metrics import daily_change
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.transactions import Transaction
from financial_app.domain.view_scope import ScopeEntry, in_scope, parse_scope, scope_entries, scope_setting
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.settings import VIEW_SCOPE, load_setting, save_setting
from financial_app.ui.changes import Change

TOTAL_LABEL = "Total"
NO_VALUE = "—"


class ViewScope:
    """A window's View Scope: ``account_id`` ``None`` for Total, else that Account's id."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        accounts = {account.id for account in list_accounts(engine)}
        self.account_id = parse_scope(load_setting(engine, VIEW_SCOPE), accounts)
        self.listeners: list[Callable[[], None]] = []

    def on_change(self, listener: Callable[[], None]) -> None:
        self.listeners.append(listener)

    def switch(self, account_id: int | None) -> None:
        """Change and remember the scope, then redraw whatever follows it."""
        self.account_id = account_id
        save_setting(self.engine, VIEW_SCOPE, scope_setting(account_id))
        for listener in self.listeners:
            listener()

    @property
    def name(self) -> str:
        """Total, or the Account's name (Total again when the Account is gone)."""
        names = {account.id: account.name for account in list_accounts(self.engine)}
        return names.get(self.account_id, TOTAL_LABEL) if self.account_id is not None else TOTAL_LABEL

    def includes(self, transaction: Transaction) -> bool:
        return in_scope(transaction, self.account_id)


class ScopeSwitcher:
    """The header's switcher; ``days`` gives History's days, ``None`` while they load."""

    # The changes it redraws on (ui/changes.py)
    CHANGES = frozenset({Change.SCOPE, Change.HISTORY})

    def __init__(self, scope: ViewScope, days: Callable[[], list[DayValue] | None]) -> None:
        self.scope = scope
        self.days = days
        self.show_inactive = False
        self.button = ui.button(on_click=self.open).props("flat no-caps color=ink icon-right=expand_more")
        self.button.mark("view-scope")
        with self.button:
            self.menu = ui.menu()
            self.menu.on_value_change(lambda _: self.entries.refresh())
            self.menu.props("anchor='bottom right' self='top right'")
            with self.menu:
                self.entries()
        self.refresh()

    def refresh(self) -> None:
        self.button.text = self.scope.name
        self.entries.refresh()

    def open(self) -> None:
        # Drawn on each opening, so a renamed or added Account shows
        self.menu.open()

    def choose(self, account_id: int | None) -> None:
        self.menu.close()
        self.scope.switch(account_id)

    def toggle_inactive(self) -> None:
        self.show_inactive = not self.show_inactive
        self.entries.refresh()

    @ui.refreshable_method
    def entries(self) -> None:
        # Only while open, so the closed menu holds no Account names
        if not self.menu.value:
            return
        days = self.days()
        entries = scope_entries(list_accounts(self.scope.engine), days)
        with ui.column().classes("gap-0 min-w-80 py-1").mark("scope-menu"):
            total = days[-1].total if days else (Decimal(0) if days is not None else None)
            change = daily_change(days) if days is not None else None
            self._row(TOTAL_LABEL, None, total, None, change)
            for entry in entries:
                if entry.active or self.show_inactive or entry.account_id == self.scope.account_id:
                    self._entry(entry)
            if any(not entry.active for entry in entries):
                label = "ukryj nieaktywne" if self.show_inactive else "pokaż nieaktywne"
                ui.button(label, on_click=self.toggle_inactive).props("flat dense no-caps size=sm").classes(
                    "self-center k-muted"
                ).mark("toggle-inactive")

    def _entry(self, entry: ScopeEntry) -> None:
        name = entry.name if entry.active else f"{entry.name} (nieaktywne)"
        self._row(name, entry.account_id, entry.value, entry.share, entry.daily_change)

    def _row(
        self, name: str, account_id: int | None, value: Decimal | None, share: Decimal | None, change: Decimal | None
    ) -> None:
        chosen = account_id == self.scope.account_id
        row = ui.element("div").classes("w-full px-4 py-2 cursor-pointer k-hover")
        row.classes("k-highlight" if chosen else "").mark(f"scope-entry scope-{scope_setting(account_id)}")
        row.on("click", lambda: self.choose(account_id))
        with row:
            with ui.row().classes("w-full items-baseline justify-between no-wrap gap-4"):
                ui.label(name).classes("font-medium")
                ui.label(NO_VALUE if value is None else format_pln(value)).classes("whitespace-nowrap")
            with ui.row().classes("w-full items-center justify-between no-wrap gap-4"):
                if account_id is not None:
                    bar = ui.linear_progress(float(share or 0), show_value=False, size="6px").classes("w-32")
                    bar.props("rounded color=primary")
                else:
                    ui.element("div")
                change_label = ui.label(NO_VALUE if change is None else format_pln(change, signed=bool(change)))
                change_label.classes("text-xs whitespace-nowrap")
                if change:
                    change_label.classes("k-gain" if change > 0 else "k-loss")
                change_label.tooltip("Zmiana dzienna")


def breadcrumbs(scope: ViewScope) -> None:
    """ "Total › <Account>" in an Account scope, "Total" returning to the Total; nothing in Total."""
    if scope.account_id is None:
        return
    with ui.row().classes("items-center gap-1 text-sm").mark("breadcrumbs"):
        ui.button(TOTAL_LABEL, on_click=lambda: scope.switch(None)).props("flat dense no-caps color=primary")
        ui.label("›").classes("k-muted")
        ui.label(scope.name).classes("font-medium")
