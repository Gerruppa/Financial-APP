"""The card of a treasury bond type (issue #185), opened from the header search: the offer on sale now from the MF
file, the user's Bond Series of the type and "Kup", which opens the transaction dialog on a Buy of the type."""

from collections.abc import Callable
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountType
from financial_app.domain.bonds import RATE_RULES, TERM_MONTHS, BondType, current_offer
from financial_app.domain.formatting import format_count, format_date, format_percent, format_pln, format_quantity
from financial_app.domain.transaction_form import BOND_TYPE_OPTIONS, FormPrefill
from financial_app.domain.transactions import TransactionType
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.bond_data import load_series_terms
from financial_app.persistence.bond_series import list_bond_series
from financial_app.sources.nbp import NbpRates
from financial_app.sources.todays_view import todays_view
from financial_app.ui.transaction_dialog import open_transaction_dialog


def open_bond_type_card(engine: Engine, rates: NbpRates, on_bought: Callable[[], None], bond_type: BondType) -> None:
    """Open the card of ``bond_type``; ``on_bought`` runs after the Buy it opens is saved."""
    dialog = ui.dialog()
    dialog.on("hide", dialog.delete)
    with dialog, ui.card().classes("w-[640px] max-w-[95vw] gap-3").mark("bond-type-card"):
        with ui.row().classes("w-full items-start no-wrap"):
            ui.label(f"Obligacje {BOND_TYPE_OPTIONS[bond_type.value]}").classes("text-2xl font-bold grow")
            ui.button(icon="close", on_click=dialog.close).props('flat round aria-label="Zamknij kartę"')
        _offer(engine, rates, bond_type)
        _own_series(engine, rates, bond_type)
        ui.button("Kup", icon="add_shopping_cart", on_click=lambda: _buy(engine, rates, on_bought, bond_type)).props(
            "no-caps"
        ).mark("bond-buy")
    dialog.open()


def _offer(engine: Engine, rates: NbpRates, bond_type: BondType) -> None:
    """The Series of the type on sale now: its sale period, first period's rate and margin or rule."""
    offer = current_offer(load_series_terms(engine).values(), bond_type, rates.today())
    with ui.column().classes("w-full gap-1").mark("bond-offer"):
        ui.label("Bieżąca oferta").classes("text-lg font-bold")
        if offer is None:
            ui.label("Tej serii nie ma teraz w sprzedaży.").classes("k-muted")
            return
        ui.label(
            f"Seria {offer.series}, w sprzedaży od {format_date(offer.sale_start)} do {format_date(offer.sale_end)}"
        )
        months = TERM_MONTHS[bond_type]
        term = (
            format_count(months // 12, "rok", "lata", "lat")
            if months % 12 == 0
            else format_count(months, "miesiąc", "miesiące", "miesięcy")
        )
        ui.label(f"Okres: {term}").mark("bond-term")
        first = offer.rates[0] if offer.rates else None
        rate = "jeszcze nieogłoszone" if first is None else format_percent(first * 100)
        ui.label(f"Oprocentowanie w 1. okresie: {rate}").mark("bond-first-rate")
        rule = RATE_RULES[bond_type]
        if offer.margin is not None:
            rule += f" ({format_percent(offer.margin * 100)})"
        ui.label(f"Oprocentowanie później: {rule}").mark("bond-rule")


def _own_series(engine: Engine, rates: NbpRates, bond_type: BondType) -> None:
    """The user's Bond Series of the type with the bonds held in each."""
    series = [s for s in list_bond_series(engine).values() if s.bond_type is bond_type]
    view = todays_view(engine, rates)
    with ui.column().classes("w-full gap-1").mark("bond-own-series"):
        ui.label("Twoje serie").classes("text-lg font-bold")
        if not series:
            ui.label("Nie masz jeszcze obligacji tego typu.").classes("k-muted")
            return
        for item in series:
            held = [p for p in view.positions if p.instrument_id == item.instrument_id]
            parts = [item.name, f"{format_quantity(sum((p.quantity for p in held), start=Decimal(0)))} szt."]
            price = view.pln_prices.get(item.instrument_id) if item.instrument_id is not None else None
            if price is not None and held:
                parts.append(f"wartość {format_pln(sum((p.value(price) for p in held), start=Decimal(0)))}")
            ui.label(" · ".join(parts)).mark("bond-own-row")


def _buy(engine: Engine, rates: NbpRates, on_bought: Callable[[], None], bond_type: BondType) -> None:
    """The transaction dialog on a Buy of ``bond_type`` today, on the first Bonds Account (else the first Account)."""
    accounts = list_accounts(engine)
    if not accounts:
        ui.notify("Najpierw dodaj konto w zakładce Ustawienia.", type="warning")
        return
    account = next((a for a in accounts if a.account_type is AccountType.BONDS), accounts[0])
    prefill = FormPrefill(account.id, TransactionType.BUY, rates.today(), bond_type=bond_type)
    open_transaction_dialog(engine, rates, on_bought, start_with=prefill)
