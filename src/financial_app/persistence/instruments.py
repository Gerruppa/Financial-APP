"""Reading and saving Asset Classes and the Instrument catalog (spec 3.2)."""

from decimal import Decimal

from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from financial_app.domain.instruments import (
    AssetClass,
    Instrument,
    InstrumentDraft,
    InstrumentError,
    validate_asset_class_name,
)
from financial_app.persistence.models import AssetClassRow, InstrumentRow, TransactionRow


def list_asset_classes(engine: Engine) -> list[AssetClass]:
    """All Asset Classes in the sheet's order, followed by those the user added."""
    with Session(engine) as session:
        rows = session.scalars(select(AssetClassRow).order_by(AssetClassRow.position))
        return [AssetClass(id=row.id, name=row.name) for row in rows]


def add_asset_class(engine: Engine, name: str) -> AssetClass:
    name = validate_asset_class_name(name)
    with Session(engine) as session, session.begin():
        _check_class_name_is_free(session, name, class_id=None)
        last = session.scalar(select(func.max(AssetClassRow.position)))
        row = AssetClassRow(name=name, position=0 if last is None else last + 1)
        session.add(row)
        _flush(session, f"Klasa aktywów o nazwie „{name}” już istnieje.")
        return AssetClass(id=row.id, name=row.name)


def rename_asset_class(engine: Engine, class_id: int, name: str) -> AssetClass:
    """Instruments refer to the class by id, so they all show the new name."""
    name = validate_asset_class_name(name)
    with Session(engine) as session, session.begin():
        row = session.get_one(AssetClassRow, class_id)
        _check_class_name_is_free(session, name, class_id)
        row.name = name
        _flush(session, f"Klasa aktywów o nazwie „{name}” już istnieje.")
        return AssetClass(id=row.id, name=row.name)


def delete_asset_class(engine: Engine, class_id: int) -> None:
    """Remove an Asset Class that no Instrument uses; one that still has Instruments is kept."""
    with Session(engine) as session, session.begin():
        row = session.get_one(AssetClassRow, class_id)
        if session.scalar(select(InstrumentRow.id).where(InstrumentRow.asset_class_id == class_id).limit(1)):
            raise InstrumentError(f"Nie można usunąć klasy „{row.name}”, bo są do niej przypisane instrumenty.")
        session.delete(row)


def list_instruments(engine: Engine) -> list[Instrument]:
    """All Instruments sorted by name."""
    with Session(engine) as session:
        rows = session.scalars(select(InstrumentRow).options(selectinload(InstrumentRow.asset_class)))
        return sorted((_to_instrument(row) for row in rows), key=lambda instrument: instrument.name.casefold())


def add_instrument(engine: Engine, draft: InstrumentDraft) -> Instrument:
    with Session(engine) as session, session.begin():
        _check_instrument_name_is_free(session, draft.name, instrument_id=None)
        row = InstrumentRow()
        _fill(session, row, draft)
        session.add(row)
        _flush(session, f"Instrument o nazwie „{draft.name}” już istnieje.")
        return _to_instrument(row)


def update_instrument(engine: Engine, instrument_id: int, draft: InstrumentDraft) -> Instrument:
    """Replace every field of the Instrument; ``manual_price=None`` clears the Manual Price."""
    with Session(engine) as session, session.begin():
        row = session.get_one(InstrumentRow, instrument_id)
        _check_instrument_name_is_free(session, draft.name, instrument_id)
        # Its Transactions' prices and NBP Rates are in the old currency
        if draft.quote_currency != row.quote_currency and session.scalar(
            select(TransactionRow.id).where(TransactionRow.instrument_id == instrument_id).limit(1)
        ):
            raise InstrumentError("Nie można zmienić waluty instrumentu, który ma już transakcje.")
        _fill(session, row, draft)
        _flush(session, f"Instrument o nazwie „{draft.name}” już istnieje.")
        return _to_instrument(row)


def delete_instrument(engine: Engine, instrument_id: int) -> None:
    """Remove an Instrument that no Transaction uses; one with Transactions is kept."""
    with Session(engine) as session, session.begin():
        row = session.get_one(InstrumentRow, instrument_id)
        if session.scalar(select(TransactionRow.id).where(TransactionRow.instrument_id == instrument_id).limit(1)):
            raise InstrumentError(f"Nie można usunąć instrumentu „{row.name}”, bo ma transakcje.")
        session.delete(row)


def _flush(session: Session, duplicate_message: str) -> None:
    try:
        session.flush()
    except IntegrityError:
        # Only the unique name can fail here; normally the _check_*_is_free functions catch it first
        raise InstrumentError(duplicate_message) from None


# Python's casefold also matches Polish letters, which SQLite's NOCASE leaves case-sensitive
def _check_class_name_is_free(session: Session, name: str, class_id: int | None) -> None:
    for other_id, other_name in session.execute(select(AssetClassRow.id, AssetClassRow.name)):
        if other_id != class_id and other_name.casefold() == name.casefold():
            raise InstrumentError(f"Klasa aktywów o nazwie „{other_name}” już istnieje.")


def _check_instrument_name_is_free(session: Session, name: str, instrument_id: int | None) -> None:
    for other_id, other_name in session.execute(select(InstrumentRow.id, InstrumentRow.name)):
        if other_id != instrument_id and other_name.casefold() == name.casefold():
            raise InstrumentError(f"Instrument o nazwie „{other_name}” już istnieje.")


def _fill(session: Session, row: InstrumentRow, draft: InstrumentDraft) -> None:
    row.name = draft.name
    asset_class = session.get(AssetClassRow, draft.asset_class_id)
    if asset_class is None:
        raise InstrumentError("Wybrana klasa aktywów nie istnieje.")
    row.asset_class = asset_class
    row.quote_currency = draft.quote_currency
    row.market = draft.market
    price = draft.manual_price
    row.manual_price = None if price is None else str(price)


def _to_instrument(row: InstrumentRow) -> Instrument:
    price = row.manual_price
    return Instrument(
        id=row.id,
        name=row.name,
        asset_class_id=row.asset_class_id,
        asset_class_name=row.asset_class.name,
        quote_currency=row.quote_currency,
        market=row.market,
        manual_price=None if price is None else Decimal(price),
    )
