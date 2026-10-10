"""An Instrument's price and its status (issue #36, spec 4.1)."""

from datetime import date
from decimal import Decimal

from financial_app.domain.instruments import Instrument
from financial_app.domain.prices import Quote
from financial_app.domain.valuation import Badge, InstrumentPrice, PriceStatus, instrument_price


def _instrument(currency: str = "PLN", manual_price: str | None = "45.12") -> Instrument:
    price = None if manual_price is None else Decimal(manual_price)
    return Instrument("PZU", 2, currency, "GPW", price, {"yahoo": "PZU.WA"}, id=1, asset_class_name="Akcje polskie")


def test_a_pln_manual_price_is_its_value_in_pln() -> None:
    price = instrument_price(_instrument(), None, lambda currency: Decimal(1))

    assert price == InstrumentPrice(Decimal("45.12"), "PLN", Decimal("45.12"), PriceStatus.MANUAL, badge=Badge.MANUAL)


def test_a_foreign_manual_price_is_converted_at_the_rate() -> None:
    price = instrument_price(_instrument("USD", "230.50"), None, {"USD": Decimal("3.6512")}.get)

    assert price == InstrumentPrice(
        Decimal("230.50"), "USD", Decimal("841.6016"), PriceStatus.MANUAL, badge=Badge.MANUAL
    )


def test_without_a_manual_price_there_is_no_price_and_no_rate_is_looked_up() -> None:
    asked: list[str] = []

    def rate_for(currency: str) -> Decimal | None:
        asked.append(currency)
        return Decimal("3.6512")

    price = instrument_price(_instrument("USD", None), None, rate_for)

    assert price == InstrumentPrice(None, "USD", None, PriceStatus.NO_PRICE)
    assert asked == []


def test_a_manual_price_without_a_rate_keeps_its_price_but_has_no_pln_value() -> None:
    price = instrument_price(_instrument("USD", "230.50"), None, lambda currency: None)

    assert price == InstrumentPrice(Decimal("230.50"), "USD", None, PriceStatus.NO_RATE, badge=Badge.MANUAL)


def test_without_a_manual_price_the_newest_quote_is_the_price() -> None:
    quote = Quote(Decimal("123.91"), "USD", date(2026, 10, 9), "yahoo")

    price = instrument_price(_instrument("USD", None), quote, {"USD": Decimal("3.9087")}.get)

    assert price == InstrumentPrice(Decimal("123.91"), "USD", Decimal("484.327017"), PriceStatus.QUOTE, quote)


def test_a_manual_price_wins_over_the_quote_which_is_kept_to_show_beside_it() -> None:
    quote = Quote(Decimal("230.00"), "USD", date(2026, 10, 9), "yahoo")

    price = instrument_price(_instrument("USD", "180"), quote, {"USD": Decimal("4")}.get)

    assert price == InstrumentPrice(Decimal("180"), "USD", Decimal("720"), PriceStatus.MANUAL, quote, Badge.MANUAL)


def _automatic(asset_class: str = "Akcje polskie", symbols: dict[str, str] | None = None) -> Instrument:
    symbols = {"yahoo": "PZU.WA"} if symbols is None else symbols
    return Instrument("PZU", 2, "PLN", "GPW", None, symbols, id=1, asset_class_name=asset_class)


def test_a_manual_price_has_the_manual_badge() -> None:
    assert instrument_price(_instrument(), None, lambda currency: Decimal(1)).badge is Badge.MANUAL


def test_a_fresh_quote_has_no_badge() -> None:
    quote = Quote(Decimal("45.12"), "PLN", date(2026, 10, 9), "yahoo")

    assert instrument_price(_automatic(), quote, lambda currency: Decimal(1)).badge is None


def test_a_quote_whose_latest_refresh_failed_still_values_the_instrument_but_is_stale() -> None:
    quote = Quote(Decimal("45.12"), "PLN", date(2026, 10, 9), "yahoo")

    price = instrument_price(_automatic(), quote, lambda currency: Decimal(1), stale=True)

    assert (price.pln, price.status, price.badge) == (Decimal("45.12"), PriceStatus.QUOTE, Badge.STALE)


def test_a_manual_price_is_never_stale() -> None:
    assert instrument_price(_instrument(), None, lambda currency: Decimal(1), stale=True).badge is Badge.MANUAL


def test_an_instrument_without_a_source_symbol_for_its_asset_class_has_no_source() -> None:
    price = instrument_price(_automatic(symbols={}), None, lambda currency: Decimal(1))

    assert (price.status, price.badge) == (PriceStatus.NO_PRICE, Badge.NO_SOURCE)


def test_a_polish_treasury_bond_waits_for_stage_3_even_with_a_manual_price() -> None:
    bond = Instrument("EDO0735", 4, "PLN", "", Decimal("104.5"), id=1, asset_class_name="Obligacje skarbowe polskie")

    price = instrument_price(bond, None, lambda currency: Decimal(1))

    assert (price.pln, price.status, price.badge) == (Decimal("104.5"), PriceStatus.MANUAL, Badge.STAGE_3)
