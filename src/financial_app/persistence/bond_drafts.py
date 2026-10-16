"""Maturity, Rollover and coupon Drafts (spec 3.4.1, L-6, L-8): computed from the saved Transactions and bond data,
and confirmed as ordinary Transactions."""

from datetime import date
from decimal import Decimal

from sqlalchemy import Engine

from financial_app.domain.bond_drafts import BondDraft, MaturityDraft, bond_drafts, coupons_entered
from financial_app.domain.bonds import DEFAULT_ROLLOVER_PRICE, BondSeries, BondType
from financial_app.domain.lots import open_positions
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.bond_data import load_series_terms
from financial_app.persistence.bond_series import drop_if_unused, load_bond_data, series_instrument
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import add_transaction, add_transactions, list_transactions


def pending_drafts(engine: Engine, day: date, account_id: int | None = None) -> list[BondDraft]:
    """The Drafts due by ``day`` in the View Scope (``account_id``, ``None`` for Total): maturities and the coupons not
    entered yet."""
    transactions = list_transactions(engine)
    # list_transactions is newest first; the FIFO engine wants entry order
    positions = open_positions(reversed(transactions))
    instruments = {i.id: i for i in list_instruments(engine)}
    accounts = list_accounts(engine)
    entered = coupons_entered(transactions)
    return bond_drafts(positions, instruments, accounts, load_bond_data(engine), day, account_id, entered)


def confirm_draft(engine: Engine, draft: BondDraft) -> None:
    """Save the Draft's Transaction: a maturity's redemption or a coupon's interest."""
    add_transaction(engine, draft.transaction())


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
        add_transactions(engine, [draft.transaction(), purchase])
    except Exception:
        drop_if_unused(engine, bought.id if created else None)
        raise
