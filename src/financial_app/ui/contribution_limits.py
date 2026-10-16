"""Contribution Limits (issue #95, spec 8.1): the limits per year in Ustawienia, this year's bars on the Dashboard and
the warning after a save leaves a year over its limit."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.contribution_limits import (
    IKZE_SELF_EMPLOYED,
    LIMITED_TYPES,
    ContributionLimitError,
    LimitBar,
    contribution_type,
    contributions,
    limit_bars,
    over_limit,
    over_limit_warning,
    parse_limit,
)
from financial_app.domain.formatting import format_exact, format_percent, format_pln
from financial_app.domain.transactions import Transaction, TransactionDraft
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.contribution_limits import add_year, delete_year, load_limits, set_limits
from financial_app.persistence.transactions import list_transactions


@dataclass
class ContributionLimitsSection:
    """Ustawienia > Limity wpłat: a row per year, an editable limit per limited type with that year's contributions."""

    engine: Engine

    def build(self) -> None:
        with ui.card().classes("w-full max-w-4xl"):
            with ui.row().classes("w-full items-center"):
                ui.label("Limity wpłat").classes("text-xl font-bold")
                ui.space()
                self.new_year = ui.input("Rok", value=str(self._next_year())).props("dense").classes("w-24")
                self.new_year.mark("limits-new-year")
                ui.button("Dodaj rok", icon="add", on_click=self._add_year).props("no-caps").mark("limits-add-year")
            ui.label(
                "Roczne limity wpłat na IKE, IKZE i OIPE, łącznie na wszystkich kontach danego typu. Liczą się wpłaty "
                "i przelewy z kont innego typu; wypłaty nie zwalniają limitu."
            ).classes("text-sm")
            self.rows()

    def refresh(self) -> None:
        """Redraw the rows, e.g. after Transactions or Accounts change their contributions."""
        self.rows.refresh()

    @ui.refreshable_method
    def rows(self) -> None:
        limits = load_limits(self.engine)
        transactions = list_transactions(self.engine)
        accounts = list_accounts(self.engine)
        for year, year_limits in limits.items():
            paid = contributions(transactions, accounts, year)
            with ui.row().classes("w-full items-start no-wrap"):
                ui.label(str(year)).classes("w-14 pt-4 font-medium")
                fields = {}
                for account_type in LIMITED_TYPES:
                    with ui.column().classes("grow gap-0"):
                        amount = year_limits[account_type]
                        field = ui.input(account_type.label, value="" if amount is None else format_exact(amount))
                        field.classes("w-full").mark(f"limit-{year}-{account_type.value}")
                        if account_type is AccountType.IKZE:
                            field.props(f'hint="{_self_employed_hint(year)}"')
                        fields[account_type] = field
                        paid_label = ui.label(f"wpłacono {format_pln(paid[account_type])}")
                        paid_label.classes("text-xs text-gray-500").mark(f"limit-paid-{year}-{account_type.value}")
                save = ui.button("Ustaw limity", on_click=lambda y=year, f=fields: self._save(y, f))
                save.props("no-caps flat").classes("mt-2").mark(f"limits-save-{year}")
                delete = ui.button(icon="delete", on_click=lambda y=year: self._delete(y))
                delete.props(f'flat round aria-label="Usuń rok {year}"').classes("mt-2").mark(f"limits-delete-{year}")

    def _save(self, year: int, fields: dict[AccountType, ui.input]) -> None:
        try:
            amounts = {account_type: parse_limit(field.value) for account_type, field in fields.items()}
        except ContributionLimitError as error:
            ui.notify(str(error), type="negative")
            return
        set_limits(self.engine, year, amounts)
        ui.notify(f"Zapisano limity wpłat na {year}.", type="positive")
        self.rows.refresh()

    def _next_year(self) -> int:
        years = list(load_limits(self.engine))
        return years[-1] + 1 if years else date.today().year

    def _add_year(self) -> None:
        text = self.new_year.value.strip()
        if not (text.isdigit() and len(text) == 4):
            ui.notify("Rok podaj czterema cyframi, np. 2025.", type="negative")
            return
        add_year(self.engine, int(text))
        self.new_year.value = str(self._next_year())
        self.rows.refresh()

    def _delete(self, year: int) -> None:
        try:
            delete_year(self.engine, year)
        except ContributionLimitError as error:
            ui.notify(str(error), type="negative")
            return
        self.rows.refresh()


def _self_employed_hint(year: int) -> str:
    amount = IKZE_SELF_EMPLOYED.get(year)
    if amount is None:
        return "Przy działalności gospodarczej limit jest wyższy"
    return f"Przy działalności gospodarczej: {format_pln(amount)}"


def limits_section(
    engine: Engine,
    transactions: Sequence[TransactionDraft],
    accounts: Sequence[Account],
    today: date,
    account_id: int | None,
) -> None:
    """The Dashboard's "Limity wpłat {rok}" card of the View Scope, nothing when it has no bar."""
    bars = limit_bars(transactions, accounts, load_limits(engine), today.year, account_id)
    if not bars:
        return
    with ui.card().classes("w-full").mark("contribution-limits"):
        ui.label(f"Limity wpłat {today.year}").classes("text-lg font-bold")
        for bar in bars:
            _bar(bar, total=account_id is None)


def _bar(bar: LimitBar, total: bool) -> None:
    with ui.column().classes("w-full gap-1").mark(f"limit-bar-{bar.account_type.value}"):
        with ui.row().classes("w-full items-baseline"):
            ui.label(bar.account_type.label).classes("font-medium")
            if not total:
                ui.label(f"łącznie na wszystkich kontach {bar.account_type.label}").classes("text-xs text-gray-500")
            ui.space()
            if bar.limit is None:
                ui.label(f"wpłacono {format_pln(bar.paid)}").classes("text-sm")
            else:
                ui.label(f"{format_pln(bar.paid)} z {format_pln(bar.limit)}").classes("text-sm")
        if bar.limit is None:
            ui.label(f"Brak limitu na {bar.year} — uzupełnij w Ustawieniach").classes("text-sm text-gray-500")
            return
        share = bar.share or Decimal(0)
        over = bool(bar.over)
        progress = ui.linear_progress(float(min(share, Decimal(1))), show_value=False, size="10px")
        progress.props(f"color={'negative' if over else 'primary'}")
        with ui.row().classes("w-full text-sm"):
            if over:
                ui.label(f"Przekroczono limit o {format_pln(bar.over or Decimal(0))}").classes("text-negative")
            else:
                ui.label(f"Pozostało {format_pln(bar.left or Decimal(0))}")
            ui.space()
            ui.label(format_percent(share * 100))


@dataclass
class LimitCheck:
    """The Transactions before a save, to warn after it once per type and year the save leaves over its limit with
    more paid than before; it never blocks the save."""

    engine: Engine
    before: list[Transaction]

    @classmethod
    def start(cls, engine: Engine, drafts: Iterable[TransactionDraft | None]) -> LimitCheck | None:
        """Before a save; given the ``drafts`` it saves (an edit's new and old form), ``None`` when none counts
        towards a limit, so most saves skip the check."""
        types = {account.id: account.account_type for account in list_accounts(engine)}
        if all(d is None or contribution_type(d, types) is None for d in drafts):
            return None
        return cls(engine, list_transactions(engine))

    def warn(self, saved: Iterable[TransactionDraft | None] | None = None) -> None:
        """After the save; ``saved`` defaults to the Transactions it added."""
        after = list_transactions(self.engine)
        if saved is None:
            known = {transaction.id for transaction in self.before}
            saved = [transaction for transaction in after if transaction.id not in known]
        drafts = [draft for draft in saved if draft is not None]
        bars = over_limit(self.before, after, list_accounts(self.engine), load_limits(self.engine), drafts)
        for bar in bars:
            ui.notify(over_limit_warning(bar), type="warning")
