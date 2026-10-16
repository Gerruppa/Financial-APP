"""Reading and saving Contribution Limits (issue #95, spec 8.1): a row per year, an amount per limited Account Type."""

from decimal import Decimal

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from financial_app.domain.accounts import AccountType
from financial_app.domain.contribution_limits import LIMITED_TYPES, ContributionLimitError
from financial_app.persistence.models import ContributionLimitRow


def load_limits(engine: Engine) -> dict[int, dict[AccountType, Decimal | None]]:
    """Every year's limits, oldest year first, each limited type in ``LIMITED_TYPES`` order."""
    with Session(engine) as session:
        rows = session.scalars(select(ContributionLimitRow))
        amounts = {(row.year, AccountType(row.account_type)): row.amount for row in rows}
    years = sorted({year for year, _ in amounts})
    return {
        year: {
            account_type: None if (amount := amounts.get((year, account_type))) is None else Decimal(amount)
            for account_type in LIMITED_TYPES
        }
        for year in years
    }


def add_year(engine: Engine, year: int) -> None:
    """Add ``year`` with no limits entered; an existing year stays as it is."""
    with Session(engine) as session, session.begin():
        for account_type in LIMITED_TYPES:
            if session.get(ContributionLimitRow, (year, account_type.value)) is None:
                session.add(ContributionLimitRow(year=year, account_type=account_type.value, amount=None))


def set_limit(engine: Engine, year: int, account_type: AccountType, amount: Decimal | None) -> None:
    """Enter or clear (``None``) the year's limit of ``account_type``."""
    with Session(engine) as session, session.begin():
        row = session.get(ContributionLimitRow, (year, account_type.value))
        if row is None:
            session.add(ContributionLimitRow(year=year, account_type=account_type.value, amount=_text(amount)))
        else:
            row.amount = _text(amount)


def delete_year(engine: Engine, year: int) -> None:
    """Remove ``year``'s row; refused while it has a limit entered."""
    if any(amount is not None for amount in load_limits(engine).get(year, {}).values()):
        raise ContributionLimitError(f"Najpierw usuń limity roku {year}, potem sam rok.")
    with Session(engine) as session, session.begin():
        session.execute(delete(ContributionLimitRow).where(ContributionLimitRow.year == year))


def _text(amount: Decimal | None) -> str | None:
    return None if amount is None else str(amount)
