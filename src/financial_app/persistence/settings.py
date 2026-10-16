"""Application settings kept as text by key in ``app_settings``."""

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from financial_app.persistence.models import AppSetting

# The user's personal Stooq API key, needed for price history (issue #33)
STOOQ_API_KEY = "stooq_api_key"
# The last View Scope, ``total`` or an Account id, and the last period of the period selector (issue #71)
VIEW_SCOPE = "view_scope"
PERIOD = "period"
# Set once the sheet's default Benchmarks were added (issue #91); clearing the data removes it, so they come back
BENCHMARKS_SEEDED = "benchmarks_seeded"
# The Monthly Income Goal of the passive-income calendar in PLN, as typed (issue #93)
PASSIVE_INCOME_GOAL = "passive_income_goal"
# The XTB import's remembered matches (L-17): an XTB account number's Account id, a ticker's Instrument id; clearing
# the data removes every key starting with ``XTB_PREFIX``, as they name ids new rows may take again
XTB_PREFIX = "xtb_"
XTB_ACCOUNT = XTB_PREFIX + "account:"
XTB_TICKER = XTB_PREFIX + "ticker:"


def load_setting(engine: Engine, key: str) -> str | None:
    with Session(engine) as session:
        row = session.get(AppSetting, key)
        return None if row is None else row.value


def save_setting(engine: Engine, key: str, value: str) -> None:
    with Session(engine) as session, session.begin():
        session.merge(AppSetting(key=key, value=value))
