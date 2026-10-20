"""Bond Series (spec 3.4.1): the Instruments named like EDO1036 in the treasury bond class, their rates from the saved
MF file and the user's corrections of them."""

from decimal import Decimal

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from financial_app.domain.bond_valuation import BondData
from financial_app.domain.bonds import TREASURY_BOND_CLASS, BondSeries, RateCorrection
from financial_app.domain.instruments import Instrument, InstrumentDraft, InstrumentError, InstrumentType
from financial_app.persistence.bond_data import (
    NBP_REFERENCE,
    bond_data_statuses,
    load_cpi,
    load_reference_rates,
    load_series_terms,
)
from financial_app.persistence.instruments import (
    add_asset_class,
    add_instrument,
    delete_instrument,
    list_asset_classes,
    list_instruments,
)
from financial_app.persistence.models import InstrumentRow, RateCorrectionRow


def list_bond_series(engine: Engine) -> dict[int, BondSeries]:
    """Every Bond Series by its Instrument id."""
    terms = load_series_terms(engine)
    corrections = _corrections(engine)
    return {
        instrument.id: BondSeries(
            instrument.id, instrument.name, terms.get(instrument.name), corrections.get(instrument.id, RateCorrection())
        )
        for instrument in list_instruments(engine)
        if instrument.is_bond_series
    }


def load_bond_data(engine: Engine) -> BondData:
    """What the Bond Series are valued from: every Series, the saved GUS CPI and the NBP reference rate, known up to
    the day it was last fetched."""
    fetched = bond_data_statuses(engine).get(NBP_REFERENCE)
    known_until = None if fetched is None or fetched.succeeded_at is None else fetched.succeeded_at.date()
    return BondData(list_bond_series(engine), load_cpi(engine), load_reference_rates(engine), known_until)


def save_rate_correction(engine: Engine, instrument_id: int, correction: RateCorrection) -> None:
    """Replace the Series' corrections; an empty one returns it to the MF file's rates."""
    with Session(engine) as session, session.begin():
        row = session.get_one(InstrumentRow, instrument_id)
        if correction == RateCorrection():
            row.rate_correction = None
        else:
            rates = ",".join("" if rate is None else str(rate) for rate in correction.rates)
            margin = None if correction.margin is None else str(correction.margin)
            row.rate_correction = RateCorrectionRow(margin=margin, rates=rates)


def series_instrument(engine: Engine, name: str) -> tuple[Instrument, bool]:
    """The Instrument of the Bond Series ``name`` and whether it was created now, on its first purchase: in the
    treasury bond class (added again if the user deleted it), in PLN, with the ISIN from the MF file.

    Raises InstrumentError when another Instrument already has the name."""
    for instrument in list_instruments(engine):
        if instrument.name.casefold() == name.casefold():
            if not instrument.is_bond_series:
                raise InstrumentError(
                    f"Instrument „{instrument.name}” już istnieje w klasie „{instrument.asset_class_name}”, więc nie "
                    "jest serią obligacji skarbowych. Zmień jego nazwę albo klasę w Ustawieniach."
                )
            return instrument, False
    key = TREASURY_BOND_CLASS.casefold()
    asset_class = next((c for c in list_asset_classes(engine) if c.name.casefold() == key), None)
    if asset_class is None:
        asset_class = add_asset_class(engine, TREASURY_BOND_CLASS)
    terms = load_series_terms(engine).get(name)
    draft = InstrumentDraft(
        name,
        asset_class.id,
        "PLN",
        isin="" if terms is None else terms.isin,
        instrument_type=InstrumentType.TREASURY_BOND,
    )
    return add_instrument(engine, draft), True


def drop_if_unused(engine: Engine, instrument_id: int | None) -> None:
    """Remove a Bond Series Instrument no Transaction uses any more (one created for a save that failed)."""
    if instrument_id is None:
        return
    try:
        delete_instrument(engine, instrument_id)
    except InstrumentError:
        pass  # other Transactions still use it


def _corrections(engine: Engine) -> dict[int, RateCorrection]:
    with Session(engine) as session:
        return {
            row.instrument_id: RateCorrection(
                None if row.margin is None else Decimal(row.margin),
                tuple(Decimal(part) if part else None for part in row.rates.split(",")) if row.rates else (),
            )
            for row in session.scalars(select(RateCorrectionRow))
        }
