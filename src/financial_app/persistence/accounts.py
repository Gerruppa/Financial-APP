"""Reading and saving Accounts (spec 3.1)."""

from decimal import Decimal

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import InstrumentedAttribute, Session, selectinload

from financial_app.domain.accounts import Account, AccountDraft, AccountError, AccountHolders, AccountType
from financial_app.domain.view_scope import scope_setting
from financial_app.persistence.models import (
    AccountCashCurrency,
    AccountRow,
    AppSetting,
    BenchmarkRow,
    StrategyRow,
    TransactionRow,
    ValuationSnapshotRow,
)
from financial_app.persistence.settings import VIEW_SCOPE, XTB_ACCOUNT


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


def account_holders(engine: Engine, account_id: int) -> AccountHolders:
    """What still names the Account, so it cannot be deleted (L-28)."""
    with Session(engine) as session:
        return _holders(session, account_id)


def delete_account(engine: Engine, account_id: int) -> None:
    """Delete an Account nothing names any more, else raise ``AccountError`` saying what holds it (L-28). A View
    Scope remembered on it goes back to Total, and a Benchmark comparing against it and its Valuation Snapshots go
    with it. An Account already
    gone (deleted in another window) is left so."""
    with Session(engine) as session, session.begin():
        row = session.get(AccountRow, account_id)
        if row is None:
            return
        refusal = _holders(session, account_id).refusal(row.name)
        if refusal is not None:
            raise AccountError(refusal)
        session.execute(delete(BenchmarkRow).where(BenchmarkRow.account_id == account_id))
        # SQLite runs without foreign keys enforced, so ON DELETE CASCADE alone would leave them
        session.execute(delete(ValuationSnapshotRow).where(ValuationSnapshotRow.account_id == account_id))
        session.delete(row)
        session.execute(
            delete(AppSetting).where(AppSetting.key == VIEW_SCOPE, AppSetting.value == scope_setting(account_id))
        )


def _holders(session: Session, account_id: int) -> AccountHolders:
    def count(column: InstrumentedAttribute[int] | InstrumentedAttribute[int | None]) -> int:
        return session.scalar(select(func.count()).select_from(TransactionRow).where(column == account_id)) or 0

    xtb = session.scalars(
        select(AppSetting.key).where(
            AppSetting.key.startswith(XTB_ACCOUNT, autoescape=True), AppSetting.value == str(account_id)
        )
    )
    return AccountHolders(
        transactions=count(TransactionRow.account_id),
        transfers_in=count(TransactionRow.target_account_id),
        strategy=session.scalar(select(StrategyRow.id).where(StrategyRow.account_id == account_id)) is not None,
        xtb_accounts=tuple(sorted(key.removeprefix(XTB_ACCOUNT) for key in xtb)),
    )


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
