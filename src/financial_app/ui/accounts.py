"""Ustawienia > Konta: the managed list of Accounts with an add/edit dialog (spec 3.1)."""

from dataclasses import dataclass
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.accounts import Account, AccountDraft, AccountError, AccountType, tax_regime_for
from financial_app.domain.formatting import format_exact, format_percent, parse_number
from financial_app.persistence.accounts import add_account, list_accounts, update_account
from financial_app.ui.dialogs import movable_dialog

ACCOUNT_TYPE_OPTIONS = {account_type.value: account_type.label for account_type in AccountType}


@dataclass
class AccountsSection:
    """The Konta card; ``refresh`` redraws the list after a save."""

    engine: Engine

    def build(self) -> None:
        with ui.card().classes("w-full max-w-4xl"):
            with ui.row().classes("w-full items-center"):
                ui.label("Konta").classes("text-xl font-bold")
                ui.space()
                ui.button("Dodaj konto", icon="add", on_click=lambda: self.open_dialog(None)).props("no-caps")
            # The marker sits outside the refreshable list so it survives a refresh
            with ui.column().classes("w-full gap-1").mark("accounts"):
                self.account_list()

    @ui.refreshable_method
    def account_list(self) -> None:
        accounts = list_accounts(self.engine)
        if not accounts:
            ui.label("Nie dodano jeszcze żadnego konta.").classes("text-gray-500")
        for account in accounts:
            self._account_row(account)

    def _account_row(self, account: Account) -> None:
        with ui.row().classes("w-full items-center no-wrap border-b py-1"):
            with ui.column().classes("gap-0 grow" + ("" if account.active else " opacity-60")):
                with ui.row().classes("items-center gap-2"):
                    ui.label(account.name).classes("font-medium")
                    ui.badge(account.account_type.label).props("outline")
                    if not account.active:
                        ui.badge("nieaktywne", color="grey")
                details = [account.broker, ", ".join(account.cash_currencies)]
                if account.fx_conversion_fee_percent is not None:
                    details.append(f"przewalutowanie {format_percent(account.fx_conversion_fee_percent)}")
                if account.exclude_fx_result:
                    details.append("bez wyniku walutowego")
                ui.label(" · ".join(d for d in details if d)).classes("text-sm text-gray-500")
            ui.button(icon="edit", on_click=lambda: self.open_dialog(account)).props(
                f'flat round aria-label="Edytuj {account.name}"'
            ).mark("edit-account")

    def open_dialog(self, account: Account | None) -> None:
        """Open a fresh form for a new Account (``None``) or for editing ``account``."""
        dialog = movable_dialog()
        dialog.on("hide", dialog.delete)
        with dialog, ui.card().classes("w-[480px]"):
            ui.label("Nowe konto" if account is None else "Edytuj konto").classes("text-lg font-bold")
            name = ui.input("Nazwa", value=account.name if account else "").classes("w-full").mark("account-name")
            broker = ui.input("Broker", value=account.broker if account else "").classes("w-full")
            broker.mark("account-broker")
            account_type = ui.select(
                ACCOUNT_TYPE_OPTIONS,
                label="Typ konta",
                value=(account.account_type if account else AccountType.REGULAR).value,
            ).classes("w-full")
            account_type.mark("account-type")
            regime = ui.label().classes("text-sm text-gray-600")
            regime.bind_text_from(account_type, "value", lambda value: tax_regime_for(AccountType(value)).summary)
            currencies = ui.input(
                "Waluty rachunku", value=", ".join(account.cash_currencies) if account else "PLN"
            ).props('hint="Kody walut oddzielone przecinkami, np. PLN, USD"')
            currencies.classes("w-full").mark("account-currencies")
            fee = account.fx_conversion_fee_percent if account else None
            fee_input = ui.input("Opłata za przewalutowanie %", value=_fee_text(fee))
            fee_input.props('hint="Zostaw puste, jeśli broker nie pobiera opłaty"').classes("w-full")
            fee_input.mark("account-fee")
            exclude_fx = ui.checkbox(
                "Wyklucz wynik walutowy z wyniku na Dashboardzie", value=account.exclude_fx_result if account else False
            ).mark("account-exclude-fx")
            active = ui.switch("Aktywne", value=account.active if account else True).mark("account-active")
            error = ui.label().classes("text-negative").mark("account-error")

            def save() -> None:
                try:
                    draft = AccountDraft(
                        name=name.value,
                        broker=broker.value,
                        account_type=AccountType(account_type.value),
                        cash_currencies=tuple(code for code in currencies.value.split(",") if code.strip()),
                        fx_conversion_fee_percent=_parse_percent(fee_input.value),
                        exclude_fx_result=exclude_fx.value,
                        active=active.value,
                    )
                    if account is None:
                        add_account(self.engine, draft)
                    else:
                        update_account(self.engine, account.id, draft)
                except AccountError as exc:
                    error.text = str(exc)
                    return
                dialog.close()
                self.account_list.refresh()

            with ui.row().classes("w-full justify-end"):
                ui.button("Anuluj", on_click=dialog.close).props("flat")
                ui.button("Zapisz", on_click=save)
        dialog.open()


def _fee_text(fee: Decimal | None) -> str:
    return "" if fee is None else format_exact(fee)


def _parse_percent(text: str) -> Decimal | None:
    """Read a percentage typed the Polish way ("0,5"); empty means no fee."""
    if not text.strip():
        return None
    try:
        return parse_number(text)
    except ValueError:
        raise AccountError(f"Opłata za przewalutowanie musi być liczbą, a nie „{text.strip()}”.") from None
