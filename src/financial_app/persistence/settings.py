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
# The Dashboard elements and tabs hidden in Wygląd i widoczność, a JSON list of their keys (issue #155); clearing the
# data keeps it, as it is how the window looks rather than data
UI_HIDDEN = "ui.hidden"
# The window's Theme, ``jasny`` or ``golden`` (issue #174); kept on clearing the data like ``UI_HIDDEN``
UI_THEME = "ui.theme"
# Whether the discreet mode blurs the amounts, ``1`` or ``0`` (kept on clearing the data like ``UI_THEME``)
UI_DISCREET = "ui.discreet"
# The keys of the header bell's notifications the user has read (issue #176), a JSON list; kept on clearing the data,
# as a key names a state (a count of Drafts, a refresh) that a stale one never matches again
UI_NOTIFICATIONS_READ = "ui.notifications_read"
# The Portfolio's "Grupuj" choice, a ``domain.portfolio_groups.Grouping`` (issue #198); kept on clearing the data
PORTFOLIO_GROUPING = "ui.portfolio_grouping"
# The last app version whose start was seen, so its first start opens "Co nowego" once (issue #200); kept on clearing
LAST_SEEN_VERSION = "ui.last_seen_version"
# The XTB import's remembered matches (L-17): an XTB account number's Account id, a ticker's Instrument id; clearing
# the data removes every key starting with ``XTB_PREFIX``, as they name ids new rows may take again
XTB_PREFIX = "xtb_"
XTB_ACCOUNT = XTB_PREFIX + "account:"
XTB_TICKER = XTB_PREFIX + "ticker:"
# The crypto import's remembered matches: an exchange's Account id, a coin's Instrument id (cleared with the XTB ones)
CRYPTO_ACCOUNT = XTB_PREFIX + "crypto-account:"
CRYPTO_COIN = XTB_PREFIX + "crypto-coin:"
CRYPTO_WALLET = XTB_PREFIX + "crypto-wallet:"


def load_setting(engine: Engine, key: str) -> str | None:
    with Session(engine) as session:
        row = session.get(AppSetting, key)
        return None if row is None else row.value


def save_setting(engine: Engine, key: str, value: str) -> None:
    with Session(engine) as session, session.begin():
        session.merge(AppSetting(key=key, value=value))
