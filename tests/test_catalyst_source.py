"""Nominal and accrued interest of Catalyst bonds from gpwcatalyst.pl (backlog L-23) and the IZ indexed nominal from
gov.pl (L-24), on saved pages."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from financial_app.domain.catalyst import BondFacts, IndexationDay
from financial_app.domain.prices import PriceSourceError
from financial_app.sources.catalyst import (
    CATALYST_LISTING,
    INDEXATION_PAGE,
    CatalystFacts,
    parse_catalyst_listing,
    parse_indexation,
)

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "catalyst" / "instrumenty-notowane.html").read_text(encoding="utf-8")
INDEXATION = (FIXTURES / "indexation" / "wspolczynniki-indeksacji.html").read_text(encoding="utf-8")
TODAY = date(2026, 10, 13)


def test_the_listing_gives_each_pln_bonds_nominal_and_accrued_interest() -> None:
    bonds = parse_catalyst_listing(LISTING)

    assert bonds["ACH0427"] == BondFacts(Decimal("1000.00"), Decimal("2.93"))
    assert bonds["DS1030"] == BondFacts(Decimal("1000.00"), Decimal("12.16"))
    assert bonds["IZ0831"] == BondFacts(Decimal("1077.07"), Decimal("2.63"))
    assert sorted(bonds) == ["ACH0427", "DS1030", "IZ0831", "PS0527", "SIR0228"]  # not the EUR table's SIR0628


def test_a_page_without_the_table_is_refused() -> None:
    with pytest.raises(PriceSourceError):
        parse_catalyst_listing("<html><body>Przerwa techniczna</body></html>")


def test_the_indexation_table_gives_each_iz_series_day_by_day() -> None:
    series = parse_indexation(INDEXATION)

    assert sorted(series) == ["IZ0831", "IZ0836"]
    iz0831 = series["IZ0831"]
    assert iz0831[0] == IndexationDay(date(2026, 9, 1), Decimal("1.06707"), Decimal("0.36"))
    assert iz0831[-1] == IndexationDay(date(2026, 10, 31), Decimal("1.07873"), Decimal("3.47"))
    assert [day.day for day in iz0831] == sorted(day.day for day in iz0831)
    assert len(iz0831) == 30 + 31
    assert IndexationDay(date(2026, 9, 30), Decimal("1.10438"), Decimal("2.18")) in series["IZ0836"]


def test_a_page_without_the_indexation_table_is_refused() -> None:
    with pytest.raises(PriceSourceError):
        parse_indexation("<html><body></body></html>")


class SavedPages:
    def __init__(self, failing: set[str] | None = None) -> None:
        self.failing = failing or set()
        self.asked: list[str] = []

    def __call__(self, url: str) -> str:
        self.asked.append(url)
        if url in self.failing:
            raise OSError("offline")
        return {CATALYST_LISTING: LISTING, INDEXATION_PAGE: INDEXATION}[url]


def test_a_corporate_bond_takes_its_facts_from_catalyst() -> None:
    assert CatalystFacts(SavedPages()).of("ach0427", TODAY) == BondFacts(Decimal("1000.00"), Decimal("2.93"))


def test_an_iz_bond_takes_the_indexed_nominal_and_interest_of_its_quotes_day_from_gov_pl() -> None:
    facts = CatalystFacts(SavedPages())

    assert facts.of("IZ0831", TODAY) == BondFacts(Decimal("1076.86"), Decimal("2.53"))  # 1,07686 and 2,53
    assert facts.of("IZ0831", date(2026, 9, 1)) == BondFacts(Decimal("1067.07"), Decimal("0.36"))


def test_an_iz_bond_falls_back_to_catalyst_when_gov_pl_fails() -> None:
    facts = CatalystFacts(SavedPages({INDEXATION_PAGE})).of("IZ0831", TODAY)

    assert facts == BondFacts(Decimal("1077.07"), Decimal("2.63"))


def test_each_page_is_fetched_once_a_refresh_and_again_after_a_new_refresh() -> None:
    pages = SavedPages()
    facts = CatalystFacts(pages)
    for symbol in ("ACH0427", "DS1030", "IZ0831", "IZ0836"):
        facts.of(symbol, TODAY)

    facts.new_refresh()
    facts.of("ACH0427", TODAY)

    assert pages.asked == [CATALYST_LISTING, INDEXATION_PAGE, CATALYST_LISTING]


def test_a_bond_catalyst_does_not_list_is_an_error() -> None:
    with pytest.raises(PriceSourceError, match="XYZ0130"):
        CatalystFacts(SavedPages()).of("XYZ0130", TODAY)


def test_catalyst_failing_is_an_error_for_a_corporate_bond() -> None:
    with pytest.raises(PriceSourceError, match="gpwcatalyst.pl"):
        CatalystFacts(SavedPages({CATALYST_LISTING})).of("ACH0427", TODAY)
