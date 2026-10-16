"""A Catalyst bond's price per bond from its percent of nominal (backlog L-23) and the IZ indexed nominal (L-24)."""

from datetime import date
from decimal import Decimal

from financial_app.domain.catalyst import BondFacts, IndexationDay, bond_price, indexed_facts, is_indexed


def test_a_bond_at_101_percent_of_1000_with_2_93_accrued_is_worth_1012_93() -> None:
    facts = BondFacts(nominal=Decimal("1000.00"), accrued_interest=Decimal("2.93"))

    assert bond_price(Decimal("101.00"), facts) == Decimal("1012.93")


def test_a_bond_of_100_nominal_at_99_5_percent_is_worth_99_50_plus_its_interest() -> None:
    facts = BondFacts(nominal=Decimal("100.00"), accrued_interest=Decimal("0.41"))

    assert bond_price(Decimal("99.5"), facts) == Decimal("99.91")


def test_only_iz_series_are_indexed() -> None:
    assert is_indexed("IZ0831")
    assert is_indexed("iz0836")
    assert not is_indexed("DS1030")
    assert not is_indexed("IZ083")


def test_the_indexed_nominal_is_the_coefficient_times_1000_rounded_to_the_grosz() -> None:
    days = [
        IndexationDay(date(2026, 10, 12), Decimal("1.07673"), Decimal("2.51")),
        IndexationDay(date(2026, 10, 13), Decimal("1.076835"), Decimal("2.56")),
        IndexationDay(date(2026, 10, 14), Decimal("1.07694"), Decimal("2.61")),
    ]

    assert indexed_facts(days, date(2026, 10, 13)) == BondFacts(Decimal("1076.84"), Decimal("2.56"))


def test_without_today_in_the_table_the_last_day_before_it_stands() -> None:
    days = [
        IndexationDay(date(2026, 9, 30), Decimal("1.07533"), Decimal("1.86")),
        IndexationDay(date(2026, 10, 15), Decimal("1.07900"), Decimal("0.10")),
    ]

    assert indexed_facts(days, date(2026, 10, 3)) == BondFacts(Decimal("1075.33"), Decimal("1.86"))


def test_a_table_more_than_a_week_old_gives_nothing() -> None:
    days = [IndexationDay(date(2026, 9, 30), Decimal("1.07533"), Decimal("1.86"))]

    assert indexed_facts(days, date(2026, 10, 7)) is not None
    assert indexed_facts(days, date(2026, 10, 8)) is None


def test_a_table_starting_after_today_gives_nothing() -> None:
    days = [IndexationDay(date(2026, 11, 2), Decimal("1.079"), Decimal("0.10"))]

    assert indexed_facts(days, date(2026, 10, 13)) is None
