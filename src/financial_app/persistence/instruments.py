"""Reading and saving Asset Classes and the Instrument catalog (spec 3.2)."""

from collections.abc import Iterable, Mapping
from dataclasses import replace
from decimal import Decimal

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from financial_app.domain.instruments import (
    AssetClass,
    DistributionPolicy,
    Instrument,
    InstrumentDraft,
    InstrumentError,
    validate_asset_class_name,
)
from financial_app.domain.prices import HISTORY_SOURCES, OTHER, default_fallback_order, validate_fallback_order
from financial_app.persistence.history import forget_quote_history
from financial_app.persistence.models import (
    AssetClassRow,
    BenchmarkRow,
    ClassTargetRow,
    InstrumentRow,
    InstrumentTargetRow,
    MultiAssetShareRow,
    PriceFailureRow,
    QuoteRow,
    RecurringRuleRow,
    SourceSymbolRow,
    TransactionRow,
)


def list_asset_classes(engine: Engine) -> list[AssetClass]:
    """All Asset Classes in the sheet's order, followed by those the user added."""
    with Session(engine) as session:
        rows = session.scalars(select(AssetClassRow).order_by(AssetClassRow.position))
        return [_to_asset_class(row) for row in rows]


def add_asset_class(engine: Engine, name: str, fallback_order: Iterable[str] | None = None) -> AssetClass:
    """A new Asset Class at the end of the list; without a ``fallback_order`` it gets the order of "Inne"."""
    name = validate_asset_class_name(name)
    with Session(engine) as session, session.begin():
        _check_class_name_is_free(session, name, class_id=None)
        if fallback_order is None:
            order = _new_class_fallback_order(session)
        else:
            order = validate_fallback_order(fallback_order)
        last = session.scalar(select(func.max(AssetClassRow.position)))
        row = AssetClassRow(
            name=name, position=0 if last is None else last + 1, fallback_order=fallback_order_column(order)
        )
        session.add(row)
        _flush(session, f"Klasa aktywów o nazwie „{name}” już istnieje.")
        return _to_asset_class(row)


def new_class_fallback_order(engine: Engine) -> tuple[str, ...]:
    """The Fallback Order a class the user adds starts with: that of "Inne", or its default once "Inne" was renamed."""
    with Session(engine) as session:
        return _new_class_fallback_order(session)


def _new_class_fallback_order(session: Session) -> tuple[str, ...]:
    row = session.scalar(select(AssetClassRow).where(AssetClassRow.name == OTHER))
    return default_fallback_order(OTHER) if row is None else _fallback_order(row)


def rename_asset_class(engine: Engine, class_id: int, name: str) -> AssetClass:
    """Instruments refer to the class by id, so they all show the new name."""
    name = validate_asset_class_name(name)
    with Session(engine) as session, session.begin():
        row = session.get_one(AssetClassRow, class_id)
        _check_class_name_is_free(session, name, class_id)
        row.name = name
        _flush(session, f"Klasa aktywów o nazwie „{name}” już istnieje.")
        return _to_asset_class(row)


def set_fallback_order(engine: Engine, class_id: int, fallback_order: Iterable[str]) -> AssetClass:
    """Replace the Asset Class's Fallback Order; the next price refresh tries its Instruments in it."""
    order = validate_fallback_order(fallback_order)
    with Session(engine) as session, session.begin():
        row = session.get_one(AssetClassRow, class_id)
        row.fallback_order = fallback_order_column(order)
        return _to_asset_class(row)


def update_asset_class(engine: Engine, class_id: int, name: str, fallback_order: Iterable[str]) -> AssetClass:
    """Rename the Asset Class and replace its Fallback Order, both or neither."""
    name = validate_asset_class_name(name)
    order = validate_fallback_order(fallback_order)
    with Session(engine) as session, session.begin():
        row = session.get_one(AssetClassRow, class_id)
        _check_class_name_is_free(session, name, class_id)
        row.name = name
        row.fallback_order = fallback_order_column(order)
        _flush(session, f"Klasa aktywów o nazwie „{name}” już istnieje.")
        return _to_asset_class(row)


def delete_asset_class(engine: Engine, class_id: int) -> None:
    """Remove an Asset Class that no Instrument, Multi-asset Split or Allocation Target uses."""
    with Session(engine) as session, session.begin():
        row = session.get_one(AssetClassRow, class_id)
        if session.scalar(select(InstrumentRow.id).where(InstrumentRow.asset_class_id == class_id).limit(1)):
            raise InstrumentError(f"Nie można usunąć klasy „{row.name}”, bo są do niej przypisane instrumenty.")
        split_by = session.scalar(
            select(InstrumentRow.name)
            .join(MultiAssetShareRow, MultiAssetShareRow.instrument_id == InstrumentRow.id)
            .where(MultiAssetShareRow.asset_class_id == class_id)
            .limit(1)
        )
        if split_by:
            raise InstrumentError(
                f"Nie można usunąć klasy „{row.name}”, bo jest w podziale Multi-asset instrumentu „{split_by}”."
            )
        if session.scalar(select(ClassTargetRow.strategy_id).where(ClassTargetRow.asset_class_id == class_id).limit(1)):
            raise InstrumentError(f"Nie można usunąć klasy „{row.name}”, bo ma cel w strategii inwestycyjnej.")
        session.delete(row)


def list_instruments(engine: Engine) -> list[Instrument]:
    """All Instruments sorted by name."""
    with Session(engine) as session:
        rows = session.scalars(
            select(InstrumentRow).options(
                selectinload(InstrumentRow.asset_class),
                selectinload(InstrumentRow.source_symbols),
                selectinload(InstrumentRow.multi_asset_split).selectinload(MultiAssetShareRow.asset_class),
            )
        )
        return sorted((_to_instrument(row) for row in rows), key=lambda instrument: instrument.name.casefold())


def get_instrument(engine: Engine, instrument_id: int) -> Instrument:
    with Session(engine) as session:
        return _to_instrument(session.get_one(InstrumentRow, instrument_id))


def add_instrument(engine: Engine, draft: InstrumentDraft) -> Instrument:
    with Session(engine) as session, session.begin():
        _check_instrument_name_is_free(session, draft.name, instrument_id=None)
        row = InstrumentRow()
        _fill(session, row, draft)
        session.add(row)
        _flush(session, f"Instrument o nazwie „{draft.name}” już istnieje.")
        return _to_instrument(row)


def update_instrument(engine: Engine, instrument_id: int, draft: InstrumentDraft) -> Instrument:
    """Replace every field of the Instrument; ``manual_price=None`` clears the Manual Price, and Source Symbols not in
    the draft are removed."""
    with Session(engine) as session, session.begin():
        row = session.get_one(InstrumentRow, instrument_id)
        _check_instrument_name_is_free(session, draft.name, instrument_id)
        # History fetched for another Yahoo, analizy.pl or Stooq symbol is not this one's; they ignore the case
        saved = _to_instrument(row).source_symbols
        if any(
            (draft.source_symbols.get(source) or "").lower() != (saved.get(source) or "").lower()
            for source in HISTORY_SOURCES
        ):
            forget_quote_history(session, instrument_id)
        # Its Transactions' prices and NBP Rates are in the old currency
        if draft.quote_currency != row.quote_currency and session.scalar(
            select(TransactionRow.id).where(TransactionRow.instrument_id == instrument_id).limit(1)
        ):
            raise InstrumentError("Nie można zmienić waluty instrumentu, który ma już transakcje.")
        _fill(session, row, draft)
        _flush(session, f"Instrument o nazwie „{draft.name}” już istnieje.")
        return _to_instrument(row)


def set_multi_asset_split(engine: Engine, instrument_id: int, split: Mapping[int, Decimal]) -> Instrument:
    """Replace only the Instrument's Multi-asset Split (percent by Asset Class id; empty for none)."""
    with Session(engine) as session, session.begin():
        row = session.get_one(InstrumentRow, instrument_id)
        # Replacing it validates the split like a draft's
        validated = replace(_to_instrument(row), multi_asset_split=split)
        _fill_split(session, row, validated.multi_asset_split)
        session.flush()
        return _to_instrument(row)


def delete_instrument(engine: Engine, instrument_id: int) -> None:
    """Remove an Instrument that no Transaction or Recurring Rule uses, with its Instrument Targets and Benchmarks;
    one with Transactions or bought by a Recurring Rule is kept."""
    with Session(engine) as session, session.begin():
        row = session.get_one(InstrumentRow, instrument_id)
        if session.scalar(select(TransactionRow.id).where(TransactionRow.instrument_id == instrument_id).limit(1)):
            raise InstrumentError(f"Nie można usunąć instrumentu „{row.name}”, bo ma transakcje.")
        if session.scalar(select(RecurringRuleRow.id).where(RecurringRuleRow.instrument_id == instrument_id).limit(1)):
            raise InstrumentError(f"Nie można usunąć instrumentu „{row.name}”, bo kupuje go reguła cykliczna.")
        forget_quote_history(session, instrument_id)
        session.execute(delete(QuoteRow).where(QuoteRow.instrument_id == instrument_id))
        session.execute(delete(PriceFailureRow).where(PriceFailureRow.instrument_id == instrument_id))
        session.execute(delete(InstrumentTargetRow).where(InstrumentTargetRow.instrument_id == instrument_id))
        session.execute(delete(BenchmarkRow).where(BenchmarkRow.instrument_id == instrument_id))
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
    row.isin = draft.isin
    row.manual_price = _text(draft.manual_price)
    row.metal_grams = _text(draft.metal_grams)
    row.buyback_spread_percent = _text(draft.buyback_spread_percent)
    row.ter_percent = _text(draft.ter_percent)
    row.distribution_policy = None if draft.distribution_policy is None else draft.distribution_policy.value
    row.domicile = draft.domicile
    row.quantity_decimals = draft.quantity_decimals
    row.source_symbols = [
        SourceSymbolRow(source=source, symbol=symbol) for source, symbol in draft.source_symbols.items()
    ]
    _fill_split(session, row, draft.multi_asset_split)


def _fill_split(session: Session, row: InstrumentRow, split: Mapping[int, Decimal]) -> None:
    shares = []
    for class_id, percent in split.items():
        asset_class = session.get(AssetClassRow, class_id)
        if asset_class is None:
            raise InstrumentError("Klasa aktywów z podziału Multi-asset nie istnieje.")
        shares.append(MultiAssetShareRow(asset_class=asset_class, percent=str(percent)))
    # The old rows go first, so a share of the same class is inserted anew rather than clashing with its old row
    row.multi_asset_split = []
    session.flush()
    row.multi_asset_split = shares


def _text(number: Decimal | None) -> str | None:
    return None if number is None else str(number)


def _decimal(text: str | None) -> Decimal | None:
    return None if text is None else Decimal(text)


def fallback_order_column(order: Iterable[str]) -> str:
    """A Fallback Order as ``asset_classes.fallback_order`` stores it: the source keys, comma-separated."""
    return ",".join(order)


def _fallback_order(row: AssetClassRow) -> tuple[str, ...]:
    return tuple(row.fallback_order.split(",")) if row.fallback_order else ()


def _to_asset_class(row: AssetClassRow) -> AssetClass:
    return AssetClass(id=row.id, name=row.name, fallback_order=_fallback_order(row), multi_asset=row.multi_asset)


def _to_instrument(row: InstrumentRow) -> Instrument:
    # In the Asset Classes' order, like everywhere else they are listed
    shares = sorted(row.multi_asset_split, key=lambda share: share.asset_class.position)
    return Instrument(
        id=row.id,
        name=row.name,
        asset_class_id=row.asset_class_id,
        asset_class_name=row.asset_class.name,
        fallback_order=_fallback_order(row.asset_class),
        in_multi_asset_class=row.asset_class.multi_asset,
        quote_currency=row.quote_currency,
        market=row.market,
        isin=row.isin,
        manual_price=_decimal(row.manual_price),
        source_symbols={s.source: s.symbol for s in row.source_symbols},
        metal_grams=_decimal(row.metal_grams),
        buyback_spread_percent=_decimal(row.buyback_spread_percent),
        ter_percent=_decimal(row.ter_percent),
        distribution_policy=None if row.distribution_policy is None else DistributionPolicy(row.distribution_policy),
        domicile=row.domicile,
        quantity_decimals=row.quantity_decimals,
        multi_asset_split={share.asset_class_id: Decimal(share.percent) for share in shares},
        split_class_names={share.asset_class_id: share.asset_class.name for share in shares},
    )
