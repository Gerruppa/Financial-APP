"""Reading, saving, editing and deleting Transactions (spec 3.3)."""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import Engine, select, tuple_
from sqlalchemy.orm import Session

from financial_app.domain.currencies import NbpRate
from financial_app.domain.lots import open_positions
from financial_app.domain.transactions import PLN, Transaction, TransactionDraft, TransactionError, TransactionType
from financial_app.persistence.models import AccountRow, InstrumentRow, TransactionRow


def list_transactions(engine: Engine) -> list[Transaction]:
    """All Transactions, newest first; same-day ones in reverse entry order."""
    with Session(engine) as session:
        rows = session.scalars(select(TransactionRow).order_by(TransactionRow.date.desc(), TransactionRow.id.desc()))
        return [_to_transaction(row) for row in rows]


def add_transaction(engine: Engine, draft: TransactionDraft) -> Transaction:
    """Save ``draft``; a Sell not covered by the Account's Lots raises InsufficientQuantityError (spec 3.3)."""
    [saved] = add_transactions(engine, [draft])
    return saved


def add_transactions(engine: Engine, drafts: Sequence[TransactionDraft]) -> list[Transaction]:
    """Save ``drafts`` in this entry order, all or none (e.g. an automatic Currency Exchange with its Buy)."""
    with Session(engine) as session, session.begin():
        saved = []
        for draft in drafts:
            _check_references(session, draft)
            _check_coverage(session, draft, replacing=None)
            row = TransactionRow()
            _fill(row, draft)
            session.add(row)
            session.flush()
            saved.append(_to_transaction(row))
        return saved


def update_transaction(engine: Engine, transaction_id: int, draft: TransactionDraft) -> Transaction:
    """Replace the Transaction's fields with ``draft``; it keeps its id and so its place in the same-day order.

    Blocked with InsufficientQuantityError if a Sell, this one or a later one, would lose its cover.
    """
    with Session(engine) as session, session.begin():
        row = _get(session, transaction_id)
        _check_references(session, draft)
        _check_coverage(session, draft, replacing=row)
        _fill(row, draft)
        session.flush()
        return _to_transaction(row)


def delete_transaction(engine: Engine, transaction_id: int) -> None:
    """Delete the Transaction; blocked with InsufficientQuantityError if a later Sell would lose its cover."""
    with Session(engine) as session, session.begin():
        row = _get(session, transaction_id)
        _check_coverage(session, None, replacing=row)
        session.delete(row)


def _get(session: Session, transaction_id: int) -> TransactionRow:
    row = session.get(TransactionRow, transaction_id)
    if row is None:
        raise TransactionError("Ta transakcja nie istnieje.")
    return row


def _check_references(session: Session, draft: TransactionDraft) -> None:
    # SQLite does not enforce foreign keys unless asked to, so check the references here
    account = session.get(AccountRow, draft.account_id)
    if account is None:
        raise TransactionError("Wybrane konto nie istnieje.")
    held = {cash.currency for cash in account.cash_currencies}
    if draft.cash_currency != PLN and draft.cash_currency not in held:
        raise TransactionError(f"Konto {account.name} nie ma waluty rachunku {draft.cash_currency}.")
    if draft.instrument_id is not None:
        instrument = session.get(InstrumentRow, draft.instrument_id)
        if instrument is None:
            raise TransactionError("Wybrany instrument nie istnieje.")
        # The Tax Amount of a foreign-currency Buy, Sell or Dividend needs the NBP Rate: never silently 0 zł (spec 9.3)
        currency = instrument.quote_currency
        if currency == "PLN" and draft.nbp_rate is not None:
            raise TransactionError("Instrument w PLN nie potrzebuje kursu NBP.")
        if currency != "PLN" and draft.nbp_rate is None:
            raise TransactionError(f"Brak kursu NBP {currency}. Zapis zablokowany.")
        if draft.nbp_rate is not None and draft.nbp_rate.currency != currency:
            raise TransactionError(f"Kurs NBP musi być kursem waluty instrumentu ({currency}).")
    if draft.nbp_rate is not None and draft.nbp_rate.published_on >= draft.date:
        raise TransactionError("Kurs NBP musi pochodzić z dnia roboczego przed datą transakcji.")


def _check_coverage(session: Session, draft: TransactionDraft | None, replacing: TransactionRow | None) -> None:
    """Replay the Positions ``draft`` and ``replacing`` touch, with ``draft`` in place of ``replacing``.

    A new ``draft`` (``replacing`` is None) comes last in entry order; ``draft`` None deletes ``replacing``.
    Replaying the whole Position means a backdated change cannot uncover a later Sell either.
    """
    pairs = {
        (t.account_id, t.instrument_id) for t in (draft, replacing) if t is not None and t.instrument_id is not None
    }
    if not pairs:
        return
    rows = session.scalars(
        select(TransactionRow)
        .where(tuple_(TransactionRow.account_id, TransactionRow.instrument_id).in_(pairs))
        .order_by(TransactionRow.id)
    )
    # The edited Transaction keeps its id, so its draft takes the row's place in entry order
    transactions = [draft if row is replacing else _to_transaction(row) for row in rows]
    if replacing is None:
        transactions.append(draft)
    open_positions(t for t in transactions if t is not None)


def _fill(row: TransactionRow, draft: TransactionDraft) -> None:
    row.account_id = draft.account_id
    row.date = draft.date
    row.transaction_type = draft.transaction_type.value
    row.actual_amount = str(draft.actual_amount)
    row.comment = draft.comment
    row.instrument_id = draft.instrument_id
    row.quantity = _text(draft.quantity)
    row.price = _text(draft.price)
    row.commission = str(draft.commission) if draft.transaction_type.is_buy_or_sell else None
    row.fx_rate = _text(draft.fx_rate)
    nbp = draft.nbp_rate
    row.nbp_currency = None if nbp is None else nbp.currency
    row.nbp_rate = None if nbp is None else str(nbp.rate)
    row.nbp_published_on = None if nbp is None else nbp.published_on
    row.nbp_table = None if nbp is None else nbp.table
    row.cash_currency = draft.cash_currency
    row.to_pln = draft.to_pln
    row.fx_conversion_fee_percent = _text(draft.fx_conversion_fee_percent)
    row.gross = _text(draft.gross)
    row.withholding_tax = str(draft.withholding_tax) if draft.transaction_type.is_dividend else None


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal(text: str | None) -> Decimal | None:
    return None if text is None else Decimal(text)


def _to_transaction(row: TransactionRow) -> Transaction:
    return Transaction(
        id=row.id,
        account_id=row.account_id,
        date=row.date,
        transaction_type=TransactionType(row.transaction_type),
        actual_amount=Decimal(row.actual_amount),
        comment=row.comment,
        instrument_id=row.instrument_id,
        quantity=_decimal(row.quantity),
        price=_decimal(row.price),
        commission=Decimal(row.commission or 0),
        fx_rate=_decimal(row.fx_rate),
        nbp_rate=_nbp_rate(row),
        cash_currency=row.cash_currency,
        to_pln=row.to_pln,
        fx_conversion_fee_percent=_decimal(row.fx_conversion_fee_percent),
        gross=_decimal(row.gross),
        withholding_tax=Decimal(row.withholding_tax or 0),
    )


def _nbp_rate(row: TransactionRow) -> NbpRate | None:
    if row.nbp_rate is None:
        return None
    assert row.nbp_currency is not None and row.nbp_published_on is not None and row.nbp_table is not None
    return NbpRate(row.nbp_currency, Decimal(row.nbp_rate), row.nbp_published_on, row.nbp_table)
