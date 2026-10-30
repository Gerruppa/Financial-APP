"""Which Price Sources the price source help window advises for an Instrument (issue #274), without widgets."""

from financial_app.domain.instruments import Instrument, InstrumentType
from financial_app.domain.price_source_guide import advised_sources
from financial_app.domain.prices import ANALIZY, BANKIER, BOSSA, YAHOO


def _instrument(
    kind: InstrumentType, fallback_order: tuple[str, ...], currency: str = "PLN", market: str = ""
) -> Instrument:
    return Instrument(
        "Instrument",
        1,
        currency,
        market,
        instrument_type=kind,
        id=1,
        asset_class_name="Klasa",
        fallback_order=fallback_order,
    )


def _advised(instrument: Instrument) -> list[tuple[str, bool, bool]]:
    return [(advice.source, advice.fits, advice.in_order) for advice in advised_sources(instrument)]


def test_a_foreign_etf_is_advised_yahoo_first_then_the_other_sources_of_its_class() -> None:
    etf = _instrument(InstrumentType.ETF, (YAHOO, BOSSA), "EUR", "Xetra")

    assert _advised(etf) == [(YAHOO, True, True), (BOSSA, False, True)]


def test_a_stock_on_the_gpw_is_advised_bossa_then_yahoo() -> None:
    stock = _instrument(InstrumentType.STOCK, (BOSSA, YAHOO), market="GPW")

    assert _advised(stock) == [(BOSSA, True, True), (YAHOO, True, True)]


def test_a_fitting_source_outside_the_class_order_is_advised_but_not_in_order() -> None:
    crypto = _instrument(InstrumentType.CRYPTO, (), "USD")

    assert _advised(crypto) == [(YAHOO, True, False)]


def test_a_fund_is_advised_analizy_and_bankier() -> None:
    fund = _instrument(InstrumentType.FUND, (ANALIZY, BANKIER, YAHOO, BOSSA))

    assert _advised(fund) == [(ANALIZY, True, True), (BANKIER, True, True), (YAHOO, False, True), (BOSSA, False, True)]


def test_an_instrument_of_another_type_fits_whatever_its_class_tries() -> None:
    other = _instrument(InstrumentType.OTHER, (ANALIZY, YAHOO))

    assert _advised(other) == [(ANALIZY, True, True), (YAHOO, True, True)]


def test_every_advice_says_how_to_find_the_symbol_with_examples() -> None:
    for advice in advised_sources(_instrument(InstrumentType.OTHER, (YAHOO, BOSSA, ANALIZY, BANKIER))):
        assert advice.help.why and advice.help.find and advice.help.examples
