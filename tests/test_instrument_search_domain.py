"""What a chosen Instrument search result fills in the Instrument form (issue #25, spec 4.1)."""

from financial_app.domain.instrument_search import FormFields, SearchResult, fill_empty, looks_like_isin

ISAC = SearchResult(name="iShares MSCI ACWI", symbol="ISAC.L", market="London", currency="USD", isin="IE00B6R52259")
CDR = SearchResult(name="CD Projekt Red S.A.", symbol="CDR.WA", market="GPW", currency="PLN")


def test_a_result_fills_every_empty_field() -> None:
    filled = fill_empty(FormFields(), ISAC)

    assert filled == FormFields(isin="IE00B6R52259", quote_currency="USD", market="London", yahoo="ISAC.L")


def test_a_warsaw_result_also_gives_the_bossa_symbol() -> None:
    assert CDR.bossa_symbol == "CDR"
    assert fill_empty(FormFields(), CDR).bossa == "CDR"
    assert ISAC.bossa_symbol == ""


def test_values_already_entered_are_kept() -> None:
    entered = FormFields(isin="IE00B4L5Y983", quote_currency="EUR", market="XETRA", yahoo="IUSQ.DE", bossa="X")

    assert fill_empty(entered, ISAC) == entered


def test_blank_values_count_as_empty() -> None:
    assert fill_empty(FormFields(market="  "), ISAC).market == "London"


def test_an_unknown_currency_leaves_the_currency_alone() -> None:
    unknown = SearchResult(name="X", symbol="X.L", market="London", currency="")

    assert fill_empty(FormFields(), unknown).quote_currency == ""


def test_isin_like_queries_are_recognised() -> None:
    assert looks_like_isin(" ie00b6r52259 ")
    assert not looks_like_isin("ISAC")
    assert not looks_like_isin("iShares MSCI ACWI")
