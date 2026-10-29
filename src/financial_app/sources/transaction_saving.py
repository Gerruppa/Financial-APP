"""Saving Transactions through one interface (#110): every place that saves them (the transaction dialog, the sheet
import, the XTB Reconciliation, confirmed bond Drafts) goes through ``checked_save``, which returns what the save
warns of (``domain/save_warnings.py``), so the UI only shows it."""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import Engine

from financial_app.domain.save_warnings import SaveWarnings, save_warnings
from financial_app.domain.transactions import Transaction, TransactionDraft, covering_deposits, covering_exchange
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.bond_series import drop_if_unused, series_instrument
from financial_app.persistence.contribution_limits import load_limits
from financial_app.persistence.instruments import get_instrument, list_instruments
from financial_app.persistence.term_deposits import list_deposits
from financial_app.persistence.transactions import (
    add_transactions,
    delete_transaction,
    list_transactions,
    restore_transaction,
    transactions_in_entry_order,
    update_transaction,
)

# The comment of a proposed covering Deposit (the negative cash warning's, the crypto import's), so the user can find
# and correct it
COVERING_COMMENT = "Wpłata uzupełniająca: pokrywa brakującą gotówkę"


@dataclass(frozen=True)
class Saved[T]:
    """What the save returned, and what it warns of."""

    value: T
    warnings: SaveWarnings


def checked_save[T](engine: Engine, write: Callable[[], T]) -> Saved[T]:
    """Run ``write``, which saves Transactions all or none, and compare all the Transactions before and after it."""
    before = transactions_in_entry_order(engine)
    instruments_before = list_instruments(engine)
    value = write()
    after = transactions_in_entry_order(engine)
    warnings = save_warnings(
        before,
        after,
        list_accounts(engine),
        instruments_before,
        list_instruments(engine),
        load_limits(engine),
        list_deposits(engine),
    )
    return Saved(value, warnings)


def save_transaction(
    engine: Engine,
    draft_for: Callable[[int | None], TransactionDraft],
    *,
    edited: Transaction | None = None,
    series: str | None = None,
    with_exchange: bool = False,
) -> Saved[TransactionDraft]:
    """Add a Transaction, or replace ``edited`` with it. ``draft_for`` builds it given the id of the Bond Series
    ``series`` it buys (``None`` without one), whose Instrument is created on its first purchase and removed again if
    the save fails; an edited purchase leaving its Series removes that Series once nothing else holds it. With
    ``with_exchange`` the Exchange buying exactly its foreign cash goes first, so the Buy spends what it brings."""

    def write() -> TransactionDraft:
        created = None
        try:
            series_id = None
            if series is not None:
                bought, new = series_instrument(engine, series)
                series_id, created = bought.id, bought.id if new else None
            draft = draft_for(series_id)
            if edited is None:
                add_transactions(engine, [*([covering_exchange(draft)] if with_exchange else []), draft])
            else:
                update_transaction(engine, edited.id, draft)
        except Exception:
            drop_if_unused(engine, created)
            raise
        left = None if edited is None else edited.instrument_id
        if left is not None and left != draft.instrument_id and get_instrument(engine, left).is_bond_series:
            drop_if_unused(engine, left)
        return draft

    return checked_save(engine, write)


def covering_proposals(engine: Engine, account_ids: Iterable[int]) -> dict[int, list[TransactionDraft]]:
    """The PLN Deposits that keep each Account's cash from going below zero (``covering_deposits``), by Account id,
    for the Accounts that need any: the fix the negative cash warning offers (``SaveWarnings.short_of_pln``, #267)."""
    transactions = list_transactions(engine)
    proposed = {i: covering_deposits(transactions, i, COVERING_COMMENT) for i in dict.fromkeys(account_ids)}
    return {account_id: deposits for account_id, deposits in proposed.items() if deposits}


def save_covering(engine: Engine, deposits: Sequence[TransactionDraft]) -> Saved[list[Transaction]]:
    """Save the proposed Deposits the user kept, all or none."""
    return checked_save(engine, lambda: add_transactions(engine, deposits))


def delete_saved(engine: Engine, transaction_id: int) -> Saved[None]:
    """Delete the Transaction; raises TransactionError when that would leave a Sell uncovered."""
    return checked_save(engine, lambda: delete_transaction(engine, transaction_id))


def restore_saved(engine: Engine, transaction: Transaction) -> Saved[Transaction]:
    """Undo ``delete_saved``: put the deleted Transaction back under its id; raises TransactionError when that id was
    taken meanwhile or the Transaction would now leave a Sell uncovered."""
    return checked_save(engine, lambda: restore_transaction(engine, transaction))
