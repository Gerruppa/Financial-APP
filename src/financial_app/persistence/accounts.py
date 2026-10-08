"""Reading and saving Accounts (spec 3.1)."""

from decimal import Decimal

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from financial_app.domain.accounts import Account, AccountDraft, AccountError, AccountType
from financial_app.persistence.models import AccountCashCurrency, AccountRow


def list_accounts(engine: Engine) -> list[Account]:
    """All Accounts, active and inactive, sorted by name."""
    with Session(engine) as session:
        rows = session.scalars(select(AccountRow).options(selectinload(AccountRow.cash_currencies)))
        return sorted((_to_account(row) for row in rows), key=lambda account: account.name.casefold())


def add_account(engine: Engine, draft: AccountDraft) -> Account:
    with Session(engine) as session, session.begin():
        _check_name_is_free(session, draft.name, account_id=None)
        row = AccountRow()
        _fill(row, draft)
        session.add(row)
        _flush(session, draft.name)
        return _to_account(row)


def update_account(engine: Engine, account_id: int, draft: AccountDraft) -> Account:
    """Replace every field of the Account; deactivating is ``active=False``."""
    with Session(engine) as session, session.begin():
        row = session.get_one(AccountRow, account_id)
        _check_name_is_free(session, draft.name, account_id)
        _fill(row, draft)
        _flush(session, draft.name)
        return _to_account(row)


def _flush(session: Session, name: str) -> None:
    try:
        session.flush()
    except IntegrityError:
        # Only the unique name can fail here; normally _check_name_is_free catches it first
        raise AccountError(f"Konto o nazwie „{name}” już istnieje.") from None


def _check_name_is_free(session: Session, name: str, account_id: int | None) -> None:
    # Python's casefold also matches Polish letters, which SQLite's NOCASE leaves case-sensitive
    for other_id, other_name in session.execute(select(AccountRow.id, AccountRow.name)):
        if other_id != account_id and other_name.casefold() == name.casefold():
            raise AccountError(f"Konto o nazwie „{other_name}” już istnieje.")


def _fill(row: AccountRow, draft: AccountDraft) -> None:
    row.name = draft.name
    row.broker = draft.broker
    row.account_type = draft.account_type.value
    fee = draft.fx_conversion_fee_percent
    row.fx_conversion_fee_percent = None if fee is None else str(fee)
    row.exclude_fx_result = draft.exclude_fx_result
    row.active = draft.active
    row.cash_currencies = [
        AccountCashCurrency(currency=code, position=position) for position, code in enumerate(draft.cash_currencies)
    ]


def _to_account(row: AccountRow) -> Account:
    fee = row.fx_conversion_fee_percent
    return Account(
        id=row.id,
        name=row.name,
        broker=row.broker,
        account_type=AccountType(row.account_type),
        cash_currencies=tuple(c.currency for c in row.cash_currencies),
        fx_conversion_fee_percent=None if fee is None else Decimal(fee),
        exclude_fx_result=row.exclude_fx_result,
        active=row.active,
    )
