"""What a chosen Instrument search result fills in the Instrument form (issue #25, spec 4.1)."""

from financial_app.domain.instrument_search import FormFields, SearchResult, fill_empty, looks_like_isin
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
