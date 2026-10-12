"""Correcting a Bond Series' MF rates by hand in Ustawienia > Instrumenty (L-2, spec 3.4.1)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.bonds import RateCorrection, SeriesTerms
from financial_app.persistence.bond_data import save_series_terms
from financial_app.persistence.bond_series import list_bond_series, save_rate_correction, series_instrument
from financial_app.persistence.db import init_db
from financial_app.ui.shell import build_shell

NBSP = "\xa0"
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
    engine = init_db(tmp_path / "app.sqlite3")
    save_series_terms(engine, [EDO1036])
    return engine


def _value(user: User, marker: str) -> str:
    [field] = user.find(marker=marker).elements
    assert isinstance(field, ui.input)
    return str(field.value)


async def test_the_instruments_list_shows_a_series_rates_and_opens_them(engine: Engine) -> None:
    edo, _ = series_instrument(engine, "EDO1036")
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")

        with user.scope(marker="instruments"):
            await user.should_see(f"1. okres 5,35{NBSP}% · marża 2,00{NBSP}%")
        user.find(marker="edit-bond-rates").click()

        await user.should_see("Oprocentowanie serii EDO1036")
        assert _value(user, "bond-margin") == "2,00"
        assert _value(user, "bond-rate-1") == "5,35"
        assert _value(user, "bond-rate-2") == ""
        await user.should_see("Rok 10")


async def test_a_corrected_rate_is_saved_and_others_stay_with_the_mf_file(engine: Engine) -> None:
    edo, _ = series_instrument(engine, "EDO1036")
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-bond-rates").click()

        user.find(marker="bond-rate-2").type("4,6")
        user.find(marker="save-bond-rates").click()

        with user.scope(marker="instruments"):
            await user.should_see("poprawione ręcznie")
    series = list_bond_series(engine).get(edo.id)
    assert series is not None
    assert series.correction == RateCorrection(rates=(None, Decimal("0.046")))
    assert series.rates[:2] == (Decimal("0.0535"), Decimal("0.046"))


async def test_a_corrected_rate_shows_the_mf_one_and_can_go_back_to_it(engine: Engine) -> None:
    edo, _ = series_instrument(engine, "EDO1036")
    save_rate_correction(engine, edo.id, RateCorrection(Decimal("0.0175"), (Decimal("0.06"),)))
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-bond-rates").click()

        assert _value(user, "bond-rate-1") == "6,00"
        assert user.find(marker="bond-rate-1").elements.pop().props["hint"] == f"poprawione; w pliku MF 5,35{NBSP}%"
        assert user.find(marker="bond-rate-2").elements.pop().props["hint"] == "MF jeszcze nie podał"
        user.find(marker="restore-mf-rates").click()

        with user.scope(marker="instruments"):
            await user.should_see(f"1. okres 5,35{NBSP}% · marża 2,00{NBSP}%")
    series = list_bond_series(engine).get(edo.id)
    assert series is not None and series.correction == RateCorrection()


async def test_a_rate_that_is_no_number_is_not_saved(engine: Engine) -> None:
    edo, _ = series_instrument(engine, "EDO1036")
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/ustawienia")
        user.find(marker="edit-bond-rates").click()

        user.find(marker="bond-rate-2").type("dużo")
        user.find(marker="save-bond-rates").click()

        await user.should_see("Oprocentowanie w roku 2 musi być liczbą")
    series = list_bond_series(engine).get(edo.id)
    assert series is not None and series.correction == RateCorrection()
