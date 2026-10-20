"""What a chosen Instrument search result fills in the Instrument form (issue #25, spec 4.1)."""

import pytest

from financial_app.domain.instrument_search import (
    CombinedSearch,
    FormFields,
    FoundListing,
    InstrumentSearchError,
    fill_empty,
    looks_like_isin,
)
from financial_app.domain.instruments import DistributionPolicy
from financial_app.domain.prices import BOSSA, YAHOO

ISAC = FoundListing(
    name="iShares MSCI ACWI",
    symbol="ISAC.L",
    market="London",
    currency="USD",
    source_symbols={YAHOO: "ISAC.L"},
    isin="IE00B6R52259",
)
CDR = FoundListing(
    name="CD Projekt Red S.A.",
    symbol="CDR.WA",
    market="GPW",
    currency="PLN",
    source_symbols={YAHOO: "CDR.WA", BOSSA: "CDR"},
)


def test_a_result_fills_every_empty_field() -> None:
    filled = fill_empty(FormFields(source_symbols={YAHOO: "", BOSSA: ""}), ISAC)

    assert filled == FormFields(
        name="iShares MSCI ACWI",
        isin="IE00B6R52259",
        quote_currency="USD",
        market="London",
        source_symbols={YAHOO: "ISAC.L", BOSSA: ""},
    )


def test_every_source_symbol_of_the_result_is_filled() -> None:
    assert fill_empty(FormFields(), CDR).source_symbols == {YAHOO: "CDR.WA", BOSSA: "CDR"}


def test_values_already_entered_are_kept() -> None:
    entered = FormFields(
        name="IUSQ",
        isin="IE00B4L5Y983",
        quote_currency="EUR",
        market="XETRA",
        source_symbols={YAHOO: "IUSQ.DE", BOSSA: "X"},
        asset_class="Akcje zagraniczne",
        domicile="Irlandia",
        distribution_policy=DistributionPolicy.ACCUMULATING,
    )

    assert fill_empty(entered, CDR) == entered


def test_blank_values_count_as_empty() -> None:
    assert fill_empty(FormFields(market="  "), ISAC).market == "London"


def test_an_unknown_currency_leaves_the_currency_alone() -> None:
    unknown = FoundListing(name="X", symbol="X.L", market="London", currency="")

    assert fill_empty(FormFields(), unknown).quote_currency == ""


def test_isin_like_queries_are_recognised() -> None:
    assert looks_like_isin(" ie00b6r52259 ")
    assert not looks_like_isin("ISAC")
    assert not looks_like_isin("iShares MSCI ACWI")


def test_a_result_fills_an_empty_asset_class_only() -> None:
    stock = FoundListing(name="CDR", symbol="CDR.WA", market="GPW", currency="PLN", asset_class="Akcje polskie")

    assert fill_empty(FormFields(), stock).asset_class == "Akcje polskie"
    assert fill_empty(FormFields(asset_class="Inne"), stock).asset_class == "Inne"


# Yahoo and analizy.pl searched side by side (issue #60)


class FakeSearch:
    def __init__(self, results: list[FoundListing] | None = None, error: str = "") -> None:
        self.results = results or []
        self.error = error

    def search(self, query: str) -> list[FoundListing]:
        if self.error:
            raise InstrumentSearchError(self.error)
        return self.results


PZU60 = FoundListing(
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
        def search(self, query: str) -> list[FoundListing]:
            raise AttributeError("changed response")

    results = CombinedSearch({"Yahoo": FakeSearch([CDR]), "analizy.pl": Broken()}).search("pzu")

    assert [r.symbol for r in results] == ["CDR.WA"]
    assert results.notes == ["analizy.pl nie odpowiada"]


# A chosen result also fills the name and, for a fund, its domicile and distribution policy


ETF = FoundListing(
    name="iShares MSCI All Country World UCITS ETF USD Acc",
    symbol="ISAC.L",
    market="London",
    currency="USD",
    source_symbols={YAHOO: "ISAC.L"},
    isin="IE00B6R52259",
    fund=True,
)


def test_an_empty_name_is_filled_and_an_entered_one_kept() -> None:
    assert fill_empty(FormFields(), CDR).name == "CD Projekt Red S.A."
    assert fill_empty(FormFields(name="CDR"), CDR).name == "CDR"


def test_a_funds_domicile_comes_from_its_isins_country() -> None:
    assert fill_empty(FormFields(), ETF).domicile == "Irlandia"
    # Also from an ISIN the user typed
    no_isin = FoundListing(name="Fund", symbol="X", market="", currency="EUR", fund=True)
    assert fill_empty(FormFields(isin="LU0109392836"), no_isin).domicile == "Luksemburg"


def test_a_stocks_isin_says_nothing_about_a_domicile() -> None:
    stock = FoundListing(name="CDR", symbol="CDR.WA", market="GPW", currency="PLN", isin="PLOPTTC00011")

    assert fill_empty(FormFields(), stock).domicile == ""


def test_an_unknown_isin_country_leaves_the_domicile_empty() -> None:
    # The ISIN entered stays, so the domicile follows it rather than the result's
    assert fill_empty(FormFields(isin="XS1234567890"), ETF).domicile == ""
    no_isin = FoundListing(name="Fund", symbol="X", market="", currency="EUR", fund=True)
    assert fill_empty(FormFields(isin="XS1234567890"), no_isin).domicile == ""


@pytest.mark.parametrize(
    ("name", "policy"),
    [
        ("iShares MSCI All Country World UCITS ETF USD Acc", DistributionPolicy.ACCUMULATING),
        ("Franklin Technology Fund A (Acc) (USD", DistributionPolicy.ACCUMULATING),
        ("Vanguard FTSE All-World UCITS ETF (USD) Accumulating", DistributionPolicy.ACCUMULATING),
        ("Vanguard FTSE All-World UCITS ETF Distributing", DistributionPolicy.DISTRIBUTING),
        ("iShares Core MSCI World UCITS ETF USD (Dist)", DistributionPolicy.DISTRIBUTING),
        ("PPK inPZU 2060", None),
        ("Xtrackers MSCI World Accelerated Ltd", None),
    ],
)
def test_a_funds_distribution_policy_comes_from_its_name(name: str, policy: DistributionPolicy | None) -> None:
    fund = FoundListing(name=name, symbol="X", market="", currency="USD", fund=True)

    assert fill_empty(FormFields(), fund).distribution_policy == policy


def test_a_stocks_name_sets_no_policy() -> None:
    stock = FoundListing(name="Accenture Acc", symbol="ACN", market="NYSE", currency="USD")

    assert fill_empty(FormFields(), stock).distribution_policy is None


def test_an_entered_domicile_and_policy_are_kept() -> None:
    entered = FormFields(domicile="Luksemburg", distribution_policy=DistributionPolicy.DISTRIBUTING)

    filled = fill_empty(entered, ETF)

    assert (filled.domicile, filled.distribution_policy) == ("Luksemburg", DistributionPolicy.DISTRIBUTING)
