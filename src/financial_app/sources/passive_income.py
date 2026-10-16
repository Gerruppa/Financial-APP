"""The passive-income calendar's items (issue #93): the income received, from the saved Transactions, and the coupons
not entered yet over the next ``CALENDAR_MONTHS``, from the Bond Series held and the saved bond data."""

from datetime import date

from sqlalchemy import Engine

from financial_app.domain.bond_calendar import CALENDAR_MONTHS
from financial_app.domain.bond_drafts import coupon_drafts, coupons_entered
from financial_app.domain.bonds import add_months
from financial_app.domain.lots import open_positions
from financial_app.domain.passive_income import IncomeItem, forecast_coupons, received_income
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.bond_series import load_bond_data
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import list_transactions


def income_items(engine: Engine, today: date) -> list[IncomeItem]:
    """Every income received and the coupons due by ``CALENDAR_MONTHS`` after ``today`` not entered yet (those already
    due are Drafts to confirm), by day."""
    transactions = list_transactions(engine)
    # list_transactions is newest first; the FIFO engine wants entry order
    positions = open_positions(reversed(transactions))
    instruments = {i.id: i for i in list_instruments(engine)}
    drafts = coupon_drafts(
        positions,
        instruments,
        list_accounts(engine),
        load_bond_data(engine),
        add_months(today, CALENDAR_MONTHS),
        None,
        coupons_entered(transactions),
    )
    return sorted(received_income(transactions) + forecast_coupons(drafts), key=lambda item: item.day)
