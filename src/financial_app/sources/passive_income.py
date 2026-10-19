"""The passive-income calendar's items (issue #93): the income received, from the saved Transactions, and the coupons
not entered yet over the next ``CALENDAR_MONTHS``, from the Bond Series held and the saved bond data, with the Term
Deposits' interest not paid yet (issue #160)."""

from datetime import date

from sqlalchemy import Engine

from financial_app.domain.bond_calendar import CALENDAR_MONTHS
from financial_app.domain.bond_drafts import coupon_drafts, coupons_entered
from financial_app.domain.bonds import add_months
from financial_app.domain.lots import open_positions
from financial_app.domain.passive_income import (
    IncomeItem,
    forecast_coupons,
    forecast_deposit_interest,
    received_income,
)
from financial_app.domain.term_deposits import InterestDraft, deposit_drafts
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.bond_series import load_bond_data
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.term_deposits import list_deposits
from financial_app.persistence.transactions import transactions_in_entry_order


def income_items(engine: Engine, today: date) -> list[IncomeItem]:
    """Every income received and the coupons and deposit interest due by ``CALENDAR_MONTHS`` after ``today`` not
    entered yet (those already due are Drafts to confirm), by day."""
    transactions = transactions_in_entry_order(engine)
    positions = open_positions(transactions)
    instruments = {i.id: i for i in list_instruments(engine)}
    accounts = list_accounts(engine)
    until = add_months(today, CALENDAR_MONTHS)
    drafts = coupon_drafts(
        positions, instruments, accounts, load_bond_data(engine), until, None, coupons_entered(transactions)
    )
    interest = [
        d
        for d in deposit_drafts(list_deposits(engine), accounts, transactions, until, None)
        if isinstance(d, InterestDraft)
    ]
    items = received_income(transactions) + forecast_coupons(drafts) + forecast_deposit_interest(interest)
    return sorted(items, key=lambda item: item.day)
