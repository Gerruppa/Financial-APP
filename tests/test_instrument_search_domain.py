"""What a chosen Instrument search result fills in the Instrument form (issue #25, spec 4.1)."""

import pytest

from financial_app.domain.instrument_search import (
    CombinedSearch,
    FormFields,
    InstrumentSearchError,
    SearchResult,
    fill_empty,
    looks_like_isin,
)
from financial_app.domain.prices import BOSSA, YAHOO

ISAC = SearchResult(
    name="iShares MSCI ACWI",
    symbol="ISAC.L",
    market="London",
    currency="USD",
    source_symbols={YAHOO: "ISAC.L"},
    isin="IE00B6R52259",
)
CDR = SearchResult(
    name="CD Projekt Red S.A.",
    symbol="CDR.WA",
    market="GPW",
    currency="PLN",
    source_symbols={YAHOO: "CDR.WA", BOSSA: "CDR"},
)


def test_a_result_fills_every_empty_field() -> None:
    filled = fill_empty(FormFields(source_symbols={YAHOO: "", BOSSA: ""}), ISAC)

    assert filled == FormFields(
        isin="IE00B6R52259", quote_currency="USD", market="London", source_symbols={YAHOO: "ISAC.L", BOSSA: ""}
    )


def test_every_source_symbol_of_the_result_is_filled() -> None:
    assert fill_empty(FormFields(), CDR).source_symbols == {YAHOO: "CDR.WA", BOSSA: "CDR"}


def test_values_already_entered_are_kept() -> None:
    entered = FormFields(
        isin="IE00B4L5Y983", quote_currency="EUR", market="XETRA", source_symbols={YAHOO: "IUSQ.DE", BOSSA: "X"}
    )

    assert fill_empty(entered, CDR) == entered


def test_blank_values_count_as_empty() -> None:
    assert fill_empty(FormFields(market="  "), ISAC).market == "London"


def test_an_unknown_currency_leaves_the_currency_alone() -> None:
    unknown = SearchResult(name="X", symbol="X.L", market="London", currency="")

    assert fill_empty(FormFields(), unknown).quote_currency == ""


def test_isin_like_queries_are_recognised() -> None:
    assert looks_like_isin(" ie00b6r52259 ")
    assert not looks_like_isin("ISAC")
    assert not looks_like_isin("iShares MSCI ACWI")


def test_a_result_fills_an_empty_asset_class_only() -> None:
    stock = SearchResult(name="CDR", symbol="CDR.WA", market="GPW", currency="PLN", asset_class="Akcje polskie")

    assert fill_empty(FormFields(), stock).asset_class == "Akcje polskie"
    assert fill_empty(FormFields(asset_class="Inne"), stock).asset_class == "Inne"


# Yahoo and analizy.pl searched side by side (issue #60)


class FakeSearch:
    def __init__(self, results: list[SearchResult] | None = None, error: str = "") -> None:
        self.results = results or []
        self.error = error

    def search(self, query: str) -> list[SearchResult]:
        if self.error:
            raise InstrumentSearchError(self.error)
        return self.results


PZU60 = SearchResult(
    name="PPK inPZU 2060", symbol="PZU60", market="", currency="PLN", source_symbols={"analizy": "PZU60"}
)


def test_the_combined_search_lists_every_searchs_results_marked_with_its_source() -> None:
    combined = CombinedSearch({"Yahoo": FakeSearch([CDR]), "analizy.pl": FakeSearch([PZU60])})

    results = combined.search("pzu")

    assert [(r.symbol, r.source) for r in results] == [("CDR.WA", "Yahoo"), ("PZU60", "analizy.pl")]
    assert results.notes == []


def test_a_failing_search_leaves_the_others_results_with_a_note() -> None:
    combined = CombinedSearch({"Yahoo": FakeSearch([CDR]), "analizy.pl": FakeSearch(error="Brak sieci.")})

    results = combined.search("pzu")

    assert [r.symbol for r in results] == ["CDR.WA"]
    assert results.notes == ["analizy.pl nie odpowiada"]


def test_when_every_search_fails_the_combined_search_fails() -> None:
    combined = CombinedSearch({"Yahoo": FakeSearch(error="Yahoo: brak sieci."), "analizy.pl": FakeSearch(error="x")})

    with pytest.raises(InstrumentSearchError, match="Yahoo: brak sieci."):
        combined.search("pzu")


def test_an_unexpected_error_in_one_search_counts_as_it_not_answering() -> None:
    class Broken:
        def search(self, query: str) -> list[SearchResult]:
            raise AttributeError("changed response")

    results = CombinedSearch({"Yahoo": FakeSearch([CDR]), "analizy.pl": Broken()}).search("pzu")

    assert [r.symbol for r in results] == ["CDR.WA"]
    assert results.notes == ["analizy.pl nie odpowiada"]
