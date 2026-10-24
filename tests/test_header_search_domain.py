"""The header search's own Instruments and Search Results (issue #175), without the network."""

from datetime import date
from decimal import Decimal

from financial_app.domain.bonds import BondType, SeriesTerms, current_offer
from financial_app.domain.header_search import (
    group_results,
    matching_bond_types,
    matching_instruments,
    owned_instrument,
)
from financial_app.domain.instrument_search import FoundListing
from financial_app.domain.instruments import Instrument
from financial_app.domain.prices import ANALIZY, BOSSA, YAHOO


def _instrument(id: int, name: str, symbols: dict[str, str], isin: str = "", currency: str = "PLN") -> Instrument:
    return Instrument(
        name, 1, currency, source_symbols=symbols, isin=isin, id=id, asset_class_name="Akcje", fallback_order=()
    )


OWN_CDR = _instrument(1, "CD Projekt", {YAHOO: "CDR.WA", BOSSA: "CDR"}, isin="PLOPTTC00011")
OWN_VUAA = _instrument(2, "Vanguard S&P 500 Acc", {YAHOO: "VUAA.L"}, isin="IE00BFMXXD54", currency="USD")
OWN_ZLOTO = _instrument(3, "Złoto fizyczne", {})
OWN = [OWN_CDR, OWN_VUAA, OWN_ZLOTO]

VUAA = FoundListing(
    name="Vanguard S&P 500 UCITS ETF USD Acc",
    symbol="VUAA.L",
    market="LSE",
    currency="USD",
    source_symbols={YAHOO: "VUAA.L"},
    isin="IE00BFMXXD54",
    fund=True,
    source="Yahoo",
)
VUAG = FoundListing(
    name="Vanguard S&P 500 UCITS ETF USD Acc",
    symbol="VUAG.L",
    market="LSE",
    currency="GBP",
    source_symbols={YAHOO: "VUAG.L"},
    isin="IE00BFMXXD54",
    fund=True,
    source="Yahoo",
)
CDR = FoundListing(
    name="CD Projekt Red S.A.",
    symbol="CDR.WA",
    market="GPW",
    currency="PLN",
    source_symbols={YAHOO: "CDR.WA"},
    asset_class="Akcje polskie",
    source="Yahoo",
)
CDR_DE = FoundListing(
    name="CD Projekt Red S.A.",
    symbol="CDR.DE",
    market="XETRA",
    currency="EUR",
    source_symbols={YAHOO: "CDR.DE"},
    asset_class="Akcje zagraniczne",
    source="Yahoo",
)
QUERCUS = FoundListing(
    name="Quercus Agresywny",
    symbol="QRS32",
    market="",
    currency="PLN",
    source_symbols={ANALIZY: "QRS32"},
    fund=True,
    source="analizy.pl",
)


def test_listings_of_one_isin_or_one_name_are_one_search_result_in_the_order_found() -> None:
    found = group_results([VUAA, CDR, QUERCUS, VUAG, CDR_DE])

    assert [(f.name, f.isin, [listing.symbol for listing in f.listings]) for f in found] == [
        ("Vanguard S&P 500 UCITS ETF USD Acc", "IE00BFMXXD54", ["VUAA.L", "VUAG.L"]),
        ("CD Projekt Red S.A.", "", ["CDR.WA", "CDR.DE"]),
        ("Quercus Agresywny", "", ["QRS32"]),
    ]


def test_a_search_result_shows_each_asset_class_and_source_of_its_listings_once() -> None:
    [cdr] = group_results([CDR, CDR_DE])
    [quercus] = group_results([QUERCUS])

    assert cdr.asset_classes == ["Akcje polskie", "Akcje zagraniczne"]
    assert cdr.sources == ["Yahoo"]
    assert quercus.asset_classes == []
    assert quercus.sources == ["analizy.pl"]


def test_own_instruments_match_a_query_in_their_name_isin_or_source_symbols_ignoring_case_and_polish_letters() -> None:
    assert matching_instruments(OWN, "projekt") == [OWN_CDR]
    assert matching_instruments(OWN, "ie00bfmx") == [OWN_VUAA]
    assert matching_instruments(OWN, "vuaa") == [OWN_VUAA]
    assert matching_instruments(OWN, "cdr") == [OWN_CDR]
    assert matching_instruments(OWN, "zloto") == [OWN_ZLOTO]


def test_an_empty_query_matches_no_own_instrument_and_at_most_the_limit_are_given() -> None:
    assert matching_instruments(OWN, "  ") == []
    assert matching_instruments(OWN, "o", limit=1) == [OWN_CDR]


def test_a_listing_is_owned_when_an_instrument_has_one_of_its_source_symbols() -> None:
    assert owned_instrument(VUAA, OWN) == OWN_VUAA
    assert owned_instrument(CDR, OWN) == OWN_CDR


def test_the_same_isin_on_another_exchange_or_currency_is_not_owned() -> None:
    assert owned_instrument(VUAG, OWN) is None
    assert owned_instrument(QUERCUS, OWN) is None


def test_a_bond_type_is_found_by_its_code_ignoring_case() -> None:
    assert matching_bond_types("edo") == [BondType.EDO]
    assert matching_bond_types(" CO ") == [BondType.COI]


def test_a_bond_type_is_found_by_its_polish_term() -> None:
    assert matching_bond_types("10-letnie") == [BondType.EDO]
    assert matching_bond_types("czteroletnie") == [BondType.COI]
    assert matching_bond_types("sześcio") == [BondType.ROS]
    assert matching_bond_types("rodzinne") == [BondType.ROS, BondType.ROD]


def test_a_term_matches_from_its_start_so_that_two_years_is_not_twelve() -> None:
    assert matching_bond_types("2-letnie") == [BondType.DOR]


def test_a_single_character_or_an_unrelated_query_finds_no_bond_type() -> None:
    assert matching_bond_types("e") == []
    assert matching_bond_types("vanguard") == []


def _terms(series: str, start: date, end: date) -> SeriesTerms:
    return SeriesTerms(series, "PL", start, end, Decimal(100), None, Decimal("0.02"), (Decimal("0.0535"),), (None,))


def test_the_current_offer_is_the_series_of_the_type_on_sale_today() -> None:
    sold = [
        _terms("EDO0935", date(2025, 9, 1), date(2025, 9, 30)),
        _terms("EDO1036", date(2026, 10, 1), date(2026, 10, 31)),
        _terms("COI1030", date(2026, 10, 1), date(2026, 10, 31)),
    ]
    assert current_offer(sold, BondType.EDO, date(2026, 10, 24)) == sold[1]
    assert current_offer(sold, BondType.TOS, date(2026, 10, 24)) is None
    assert current_offer(sold, BondType.EDO, date(2026, 11, 2)) is None
