"""Reading, saving, editing and deleting Transactions (spec 3.3)."""

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from financial_app.domain.currencies import NbpRate
from financial_app.domain.lots import open_positions
from financial_app.domain.transactions import (
    PLN,
    Origin,
    SplitRatio,
    Transaction,
    TransactionDraft,
    TransactionError,
    TransactionType,
)
from financial_app.persistence.models import AccountRow, InstrumentRow, TransactionRow


def imported_external_ids(engine: Engine) -> set[str]:
    """The fingerprints of the imported Transactions already saved, so that an import skips them."""
    with Session(engine) as session:
        return set(session.scalars(select(TransactionRow.external_id).where(TransactionRow.external_id.is_not(None))))


def list_transactions(engine: Engine) -> list[Transaction]:
    """All Transactions, newest first; same-day ones in reverse entry order."""
    with Session(engine) as session:
        rows = session.scalars(select(TransactionRow).order_by(TransactionRow.date.desc(), TransactionRow.id.desc()))
        return [to_transaction(row) for row in rows]


def transactions_in_entry_order(engine: Engine) -> list[Transaction]:
    """All Transactions in the order they were saved, as the FIFO engine takes them (ADR-0003): it sorts them by date
    itself, and entry order settles same-day ties."""
    with Session(engine) as session:
        return [to_transaction(row) for row in session.scalars(select(TransactionRow).order_by(TransactionRow.id))]


def add_transaction(engine: Engine, draft: TransactionDraft) -> Transaction:
    """Save ``draft``; a Sell not covered by the Account's Lots raises InsufficientQuantityError (spec 3.3)."""
    [saved] = add_transactions(engine, [draft])
    return saved


def add_transactions(engine: Engine, drafts: Sequence[TransactionDraft]) -> list[Transaction]:
    """Save ``drafts`` in this entry order, all or none (e.g. an automatic Currency Exchange with its Buy)."""
    with Session(engine) as session, session.begin():
        saved = []
        for draft in drafts:
            check_references(session, draft)
            _check_coverage(session, draft, replacing=None)
            row = TransactionRow()
            fill_row(row, draft)
            session.add(row)
            session.flush()
            saved.append(to_transaction(row))
        return saved


def update_transaction(engine: Engine, transaction_id: int, draft: TransactionDraft) -> Transaction:
    """Replace the Transaction's fields with ``draft``; it keeps its id and so its place in the same-day order.

    Blocked with InsufficientQuantityError if a Sell, this one or a later one, would lose its cover.
    An imported Transaction keeps its Origin and fingerprint, so that importing its file again still skips it, and a
    confirmed Recurring Rule Draft the occurrence it covers (issue #97), and a Term Deposit's interest the period it
    pays (issue #160).
    """
    with Session(engine) as session, session.begin():
        row = get_row(session, transaction_id)
        draft = replace(
            draft,
            origin=Origin(row.origin),
            external_id=row.external_id,
            recurring_rule_id=row.recurring_rule_id,
            recurring_occurrence=row.recurring_occurrence,
            term_deposit_id=row.term_deposit_id,
            term_deposit_period=row.term_deposit_period,
        )
        check_references(session, draft)
        _check_coverage(session, draft, replacing=row)
        fill_row(row, draft)
        session.flush()
        return to_transaction(row)


def delete_transaction(engine: Engine, transaction_id: int) -> None:
    """Delete the Transaction; blocked with InsufficientQuantityError if a later Sell would lose its cover, and with
    TransactionError while a coupon (interest naming its Lot, L-8) names the Buy."""
    with Session(engine) as session, session.begin():
        row = get_row(session, transaction_id)
        coupons = select(TransactionRow.id).where(
            TransactionRow.lot_id == transaction_id,
            TransactionRow.transaction_type == TransactionType.DIVIDEND.value,
        )
        if session.scalar(coupons.limit(1)) is not None:
            raise TransactionError("Od tej partii zapisano odsetki; usuń je najpierw.")
        _check_coverage(session, None, replacing=row)
        session.delete(row)


def restore_transaction(engine: Engine, transaction: Transaction, dropping: Sequence[int] = ()) -> Transaction:
    """Put a deleted ``transaction`` back under its own id, so it keeps its place in the entry order (same-day ties
    settle as before) and the Sells and coupons naming its Lot find it again. The Transactions ``dropping`` names
    (the covering Deposits saved since the delete, #267) are deleted first, in the same all-or-none save, so one of
    them may have taken the id.

    Refused when another Transaction took the id meanwhile (SQLite hands a freed last id to the next row), and, like
    any save, blocked with InsufficientQuantityError if it would leave a Sell uncovered.
    """
    with Session(engine) as session, session.begin():
        for dropped in dropping:
            session.delete(get_row(session, dropped))
        session.flush()
        if session.get(TransactionRow, transaction.id) is not None:
            raise TransactionError("Miejsce tej transakcji zajęła już inna, więc nie można jej przywrócić.")
        check_references(session, transaction)
        row = TransactionRow(id=transaction.id)
        fill_row(row, transaction)
        session.add(row)
        try:
            session.flush()
        except IntegrityError as exc:
            raise TransactionError("Tej transakcji nie można przywrócić: koliduje z zapisaną.") from exc
        _check_coverage(session, transaction, replacing=row)
        return to_transaction(row)


def get_row(session: Session, transaction_id: int) -> TransactionRow:
    row = session.get(TransactionRow, transaction_id)
    if row is None:
        raise TransactionError("Ta transakcja nie istnieje.")
    return row


def check_references(session: Session, draft: TransactionDraft) -> None:
    # SQLite does not enforce foreign keys unless asked to, so check the references here
    account = session.get(AccountRow, draft.account_id)
    if account is None:
        raise TransactionError("Wybrane konto nie istnieje.")
    held = _currencies(account)
    if draft.cash_currency != PLN and draft.cash_currency not in held:
        raise TransactionError(f"Konto {account.name} nie ma waluty rachunku {draft.cash_currency}.")
    # An Account without PLN takes no PLN (#124), nor a Cash Transfer's target cash it does not hold (#125), whatever
    # the source: the dialog, an import
    moves_pln = draft.cash_change or draft.transaction_type is TransactionType.CURRENCY_EXCHANGE
    if moves_pln and PLN not in held:
        raise TransactionError(f"Konto {account.name} nie ma waluty rachunku PLN.")
    if draft.target_account_id is not None:
        target = session.get(AccountRow, draft.target_account_id)
        if target is None:
            raise TransactionError("Wybrane konto docelowe nie istnieje.")
        currency = draft.cash_currency
        if draft.transaction_type is TransactionType.CASH_TRANSFER and currency not in _currencies(target):
            raise TransactionError(f"Konto {target.name} nie ma waluty rachunku {currency}.")
    if draft.instrument_id is not None:
        instrument = session.get(InstrumentRow, draft.instrument_id)
        if instrument is None:
            raise TransactionError("Wybrany instrument nie istnieje.")
        if not draft.transaction_type.has_amount:
            return  # a Split or Security Transfer moves units only, so it needs no NBP Rate
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
    """Replay the Positions of the Instruments ``draft`` and ``replacing`` touch, with ``draft`` in place of
    ``replacing``.

    A new ``draft`` (``replacing`` is None) comes last in entry order; ``draft`` None deletes ``replacing``.
    Replaying the whole Position means a backdated change cannot uncover a later Sell or Security Transfer, or put a
    Split before the first Buy, either. Security Transfers link Positions of one Instrument on different Accounts, so
    all its Accounts are replayed.
    """
    instruments = {t.instrument_id for t in (draft, replacing) if t is not None and t.instrument_id is not None}
    if not instruments:
        return
    rows = session.scalars(
        select(TransactionRow).where(TransactionRow.instrument_id.in_(instruments)).order_by(TransactionRow.id)
    )
    # The edited Transaction keeps its id, so its draft takes the row's place in entry order and still opens the Lot a
    # Sell may name
    edited = None if draft is None or replacing is None else draft.with_id(replacing.id)
    transactions: list[TransactionDraft | None] = [edited if row is replacing else to_transaction(row) for row in rows]
    if replacing is None:
        transactions.append(draft)
    open_positions(t for t in transactions if t is not None)


def _currencies(account: AccountRow) -> set[str]:
    return {cash.currency for cash in account.cash_currencies}


def fill_row(row: TransactionRow, draft: TransactionDraft) -> None:
    row.account_id = draft.account_id
    row.date = draft.date
    row.transaction_type = draft.transaction_type.value
    row.actual_amount = str(draft.actual_amount)
    row.comment = draft.comment
    row.instrument_id = draft.instrument_id
    row.quantity = _text(draft.quantity)
    row.price = _text(draft.price)
    row.commission = str(draft.commission) if draft.transaction_type.is_buy_or_sell else None
    row.commission_currency = draft.commission_currency
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
    withheld = draft.transaction_type.is_dividend or draft.withholding_tax
    row.withholding_tax = str(draft.withholding_tax) if withheld else None
    row.target_account_id = draft.target_account_id
    ratio = draft.split_ratio
    row.split_new = None if ratio is None else ratio.new
    row.split_old = None if ratio is None else ratio.old
    row.origin = draft.origin.value
    row.external_id = draft.external_id
    row.lot_id = draft.lot_id
    row.recurring_rule_id = draft.recurring_rule_id
    row.recurring_occurrence = draft.recurring_occurrence
    row.term_deposit_id = draft.term_deposit_id
    row.term_deposit_period = draft.term_deposit_period


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal(text: str | None) -> Decimal | None:
    return None if text is None else Decimal(text)


def to_transaction(row: TransactionRow) -> Transaction:
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
        commission_currency=row.commission_currency,
        fx_rate=_decimal(row.fx_rate),
        nbp_rate=_nbp_rate(row),
        cash_currency=row.cash_currency,
        to_pln=row.to_pln,
        fx_conversion_fee_percent=_decimal(row.fx_conversion_fee_percent),
        gross=_decimal(row.gross),
        withholding_tax=Decimal(row.withholding_tax or 0),
        target_account_id=row.target_account_id,
        split_ratio=_split_ratio(row),
        origin=Origin(row.origin),
        external_id=row.external_id,
        lot_id=row.lot_id,
        recurring_rule_id=row.recurring_rule_id,
        recurring_occurrence=row.recurring_occurrence,
        term_deposit_id=row.term_deposit_id,
        term_deposit_period=row.term_deposit_period,
    )


def _split_ratio(row: TransactionRow) -> SplitRatio | None:
    if row.split_new is None or row.split_old is None:
        return None
    return SplitRatio(row.split_new, row.split_old)


def _nbp_rate(row: TransactionRow) -> NbpRate | None:
    if row.nbp_rate is None:
        return None
    assert row.nbp_currency is not None and row.nbp_published_on is not None and row.nbp_table is not None
    return NbpRate(row.nbp_currency, Decimal(row.nbp_rate), row.nbp_published_on, row.nbp_table)
