"""Bond Series as Instruments with their corrected rates (L-2, spec 3.4.1)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.bonds import TREASURY_BOND_CLASS, BondType, RateCorrection, SeriesTerms
from financial_app.domain.instruments import InstrumentDraft
from financial_app.persistence.bond_data import save_series_terms
from financial_app.persistence.bond_series import (
    list_bond_series,
    save_rate_correction,
    series_instrument,
)
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import (
    add_instrument,
    delete_instrument,
    list_asset_classes,
)
from financial_app.persistence.reset import clear_portfolio

EDO1036 = SeriesTerms(
    "EDO1036",
    "PL0000119566",
    date(2026, 10, 1),
    date(2026, 10, 31),
    Decimal(100),
    Decimal("99.9"),
    Decimal("0.02"),
    (Decimal("0.0535"), *([None] * 9)),
    (None,),
)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def test_the_first_purchase_creates_the_series_as_a_treasury_bond_instrument_with_the_mf_isin(engine: Engine) -> None:
    save_series_terms(engine, [EDO1036])

    instrument, created = series_instrument(engine, "EDO1036")

    assert created
    assert (instrument.name, instrument.asset_class_name, instrument.quote_currency, instrument.isin) == (
        "EDO1036",
        TREASURY_BOND_CLASS,
        "PLN",
        "PL0000119566",
    )
    assert instrument.is_bond_series
    assert series_instrument(engine, "EDO1036") == (instrument, False)


def test_a_series_missing_from_the_mf_file_is_created_without_an_isin(engine: Engine) -> None:
    instrument, _ = series_instrument(engine, "COI0130")

    assert instrument.isin == ""
    series = list_bond_series(engine).get(instrument.id)
    assert series is not None and series.mf is None and series.bond_type is BondType.COI


def test_bond_series_carry_their_mf_terms_and_other_instruments_are_none(engine: Engine) -> None:
    save_series_terms(engine, [EDO1036])
    edo, _ = series_instrument(engine, "EDO1036")
    shares = next(c for c in list_asset_classes(engine) if c.name == "Akcje polskie")
    cdr = add_instrument(engine, InstrumentDraft("EDO1036 akcje", shares.id, "PLN"))

    assert list_bond_series(engine) == {edo.id: list_bond_series(engine).get(edo.id)}
    assert list_bond_series(engine)[edo.id].mf == EDO1036
    assert list_bond_series(engine).get(cdr.id) is None


def test_a_correction_is_saved_replaced_and_cleared(engine: Engine) -> None:
    edo, _ = series_instrument(engine, "EDO1036")
    correction = RateCorrection(Decimal("0.0175"), (None, Decimal("0.045")))

    save_rate_correction(engine, edo.id, correction)
    series = list_bond_series(engine).get(edo.id)
    assert series is not None and series.correction == correction

    save_rate_correction(engine, edo.id, RateCorrection())
    series = list_bond_series(engine).get(edo.id)
    assert series is not None and series.correction == RateCorrection()


def test_deleting_the_series_or_clearing_the_portfolio_drops_its_correction(engine: Engine) -> None:
    edo, _ = series_instrument(engine, "EDO1036")
    save_rate_correction(engine, edo.id, RateCorrection(Decimal("0.02")))
    delete_instrument(engine, edo.id)
    coi, _ = series_instrument(engine, "COI1030")
    save_rate_correction(engine, coi.id, RateCorrection(Decimal("0.015")))

    clear_portfolio(engine)

    assert list_bond_series(engine) == {}
    # SQLite may give the new Series the old id, which must not bring the old correction back
    again, _ = series_instrument(engine, "COI1030")
    series = list_bond_series(engine).get(again.id)
    assert series is not None and series.correction == RateCorrection()
