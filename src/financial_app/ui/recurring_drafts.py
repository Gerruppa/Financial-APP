"""The "Transakcje cykliczne do zatwierdzenia" list of the Transakcje tab and its count in the header (issue #97, spec
3.3.1 point 8): each occurrence of a Recurring Rule that no Transaction covers, confirmed at once ("Zatwierdź", all
but a Buy), through the transaction dialog ("Edytuj…") or skipped ("Pomiń")."""

from collections.abc import Callable

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.currencies import MissingNbpRateError
from financial_app.domain.formatting import format_amount, format_date, format_exact
from financial_app.domain.recurring import RecurringDraft
from financial_app.domain.transaction_form import FormPrefill
from financial_app.domain.transactions import TransactionError, TransactionType
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.recurring_rules import (
    confirm_recurring_draft,
    pending_recurring_drafts,
    skip_occurrence,
)
from financial_app.sources.nbp import NbpRates
from financial_app.sources.transaction_saving import checked_save
from financial_app.ui.recurring_rules import instrument_labels
from financial_app.ui.save_warnings import show_warnings


def prefill_of(draft: RecurringDraft) -> FormPrefill:
    """The transaction dialog for a Draft: a Deposit, Cost or Cash Transfer (to its target Account) with the rule's
    amount, a Buy with its Instrument and the quantity and price left empty, as only the purchase tells them."""
    rule = draft.rule
    if rule.transaction_type is TransactionType.BUY:
        return FormPrefill(rule.account_id, rule.transaction_type, draft.due, instrument_id=rule.instrument_id)
    return FormPrefill(
        rule.account_id,
        rule.transaction_type,
        draft.due,
        amount=format_exact(rule.amount),
        cash_currency=rule.currency,
        comment=rule.name,
        target_id=rule.target_account_id,
    )


def recurring_drafts_list(
    engine: Engine,
    rates: NbpRates,
    account_id: int | None,
    edit: Callable[[RecurringDraft], None],
    on_saved: Callable[[], None],
    on_skipped: Callable[[], None],
) -> None:
    """The Drafts due in the View Scope (``account_id``), oldest first, nothing when there are none. ``edit`` opens a
    Draft in the transaction dialog; ``on_saved`` runs after one is confirmed, ``on_skipped`` after one is skipped."""
    drafts = pending_recurring_drafts(engine, rates.today(), account_id)
    if not drafts:
        return
    accounts = {account.id: account.name for account in list_accounts(engine)}
    instruments = instrument_labels(engine)
    with ui.card().classes("w-full max-w-screen-2xl mb-4 bg-amber-50").mark("recurring-drafts"):
        ui.label("Transakcje cykliczne do zatwierdzenia").classes("text-lg font-bold")
        for draft in drafts:
            rule = draft.rule
            with ui.row().classes("w-full items-center border-b py-1 gap-4").mark("recurring-draft"):
                ui.label(format_date(draft.due)).classes("w-24")
                with ui.column().classes("gap-0 grow"):
                    title = rule.name if account_id is not None else f"{rule.name} · {accounts[rule.account_id]}"
                    ui.label(title).classes("font-medium")
                    what = [rule.transaction_type.label]
                    if rule.target_account_id is not None:
                        what[0] += f" → {accounts[rule.target_account_id]}"
                    if rule.instrument_id is not None:
                        what.append(instruments[rule.instrument_id])
                    ui.label(" · ".join(what)).classes("text-sm k-muted")
                amount = format_amount(rule.amount, rule.currency)
                buying = rule.transaction_type is TransactionType.BUY
                ui.label(f"ok. {amount}" if buying else amount).classes("font-medium")
                if not buying:
                    ui.button("Zatwierdź", on_click=lambda draft=draft: _confirm(engine, rates, draft, on_saved)).props(
                        "flat"
                    ).mark("confirm-recurring")
                ui.button("Edytuj…", on_click=lambda draft=draft: edit(draft)).props("flat").mark("edit-recurring")
                ui.button("Pomiń", on_click=lambda draft=draft: _skip(engine, draft, on_skipped)).props(
                    "flat color=grey"
                ).mark("skip-recurring")


def _confirm(engine: Engine, rates: NbpRates, draft: RecurringDraft, on_saved: Callable[[], None]) -> None:
    try:
        saved = checked_save(engine, lambda: confirm_recurring_draft(engine, draft, rates.before))
    except (TransactionError, MissingNbpRateError) as exc:
        ui.notify(str(exc), type="negative")
        return
    ui.notify(f"Zapisano {draft.rule.name} z {format_date(draft.due)}.", type="positive")
    show_warnings(saved.warnings, engine=engine, on_saved=on_saved)
    on_saved()


def _skip(engine: Engine, draft: RecurringDraft, on_skipped: Callable[[], None]) -> None:
    skip_occurrence(engine, draft.rule.id, draft.due)
    ui.notify(f"Pominięto {draft.rule.name} z {format_date(draft.due)}.")
    on_skipped()
