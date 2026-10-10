"""Which Price Sources an Instrument is priced from, in which order (issue #30, spec 4.1)."""

from financial_app.domain.prices import BOSSA, YAHOO, sources_to_try


def test_an_instrument_is_tried_in_its_asset_classs_order() -> None:
    order = sources_to_try("Akcje polskie", {YAHOO: "PZU.WA", BOSSA: "PZU"})

    assert order == [(BOSSA, "PZU"), (YAHOO, "PZU.WA")]


def test_a_source_without_the_instruments_symbol_is_skipped() -> None:
    # Akcje zagraniczne try Yahoo, then Bossa; an LSE ETF has no Bossa symbol
    assert sources_to_try("Akcje zagraniczne", {YAHOO: "ISAC.L"}) == [(YAHOO, "ISAC.L")]


def test_an_asset_class_the_user_added_is_tried_like_inne() -> None:
    symbols = {YAHOO: "X", BOSSA: "Y"}

    assert sources_to_try("Nieruchomości", symbols) == sources_to_try("Inne", symbols) == [(YAHOO, "X"), (BOSSA, "Y")]


def test_cash_and_polish_treasury_bonds_are_never_fetched() -> None:
    for asset_class in ("Gotówka", "Waluty", "Obligacje skarbowe polskie"):
        assert sources_to_try(asset_class, {YAHOO: "X", BOSSA: "Y"}) == []
