"""Maturity and Rollover Drafts (spec 3.4.1, L-6): computed from the saved Transactions and bond data, and confirmed as
ordinary Transactions."""

from datetime import date
from decimal import Decimal

from sqlalchemy import Engine

from financial_app.domain.bond_drafts import MaturityDraft, maturity_drafts
from financial_app.domain.bonds import DEFAULT_ROLLOVER_PRICE, BondSeries, BondType
from financial_app.domain.lots import open_positions
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.bond_data import load_series_terms
from financial_app.persistence.bond_series import drop_if_unused, load_bond_data, series_instrument
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import add_transaction, add_transactions, list_transactions


def pending_drafts(engine: Engine, day: date, account_id: int | None = None) -> list[MaturityDraft]:
    """The Drafts due by ``day`` in the View Scope (``account_id``, ``None`` for Total)."""
    # list_transactions is newest first; the FIFO engine wants entry order
    positions = open_positions(reversed(list_transactions(engine)))
    instruments = {i.id: i for i in list_instruments(engine)}
    return maturity_drafts(positions, instruments, list_accounts(engine), load_bond_data(engine), day, account_id)


def confirm_redemption(engine: Engine, draft: MaturityDraft) -> None:
    add_transaction(engine, draft.redemption_transaction())


def rollover_price(engine: Engine, name: str) -> Decimal:
    """The price of one bond of the Series ``name`` bought in a Rollover: the MF file's, else the default."""
    series = BondSeries(None, name, load_series_terms(engine).get(name))
    return series.rollover_price or DEFAULT_ROLLOVER_PRICE


def confirm_rollover(engine: Engine, draft: MaturityDraft, bond_type: BondType, quantity: Decimal) -> None:
    """Redeem the Lot and buy ``quantity`` bonds of the ``bond_type`` Series sold that month, all or nothing; the
    Series, created on this first purchase, is removed again if the save fails."""
    name = draft.rollover_series(bond_type)
    bought, created = series_instrument(engine, name)
    try:
        purchase = draft.rollover_purchase(bought.id, quantity, rollover_price(engine, name))
        add_transactions(engine, [draft.redemption_transaction(), purchase])
    except Exception:
        drop_if_unused(engine, bought.id if created else None)
        raise
