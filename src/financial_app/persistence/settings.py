"""Application settings kept as text by key in ``app_settings``."""

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from financial_app.persistence.models import AppSetting

# The user's personal Stooq API key, needed for price history (issue #33)
STOOQ_API_KEY = "stooq_api_key"


def load_setting(engine: Engine, key: str) -> str | None:
    with Session(engine) as session:
        row = session.get(AppSetting, key)
        return None if row is None else row.value


def save_setting(engine: Engine, key: str, value: str) -> None:
    with Session(engine) as session, session.begin():
        session.merge(AppSetting(key=key, value=value))
