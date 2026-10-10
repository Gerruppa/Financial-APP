"""An Instrument's price and its status (issue #36, spec 4.1)."""

from decimal import Decimal

from financial_app.domain.instruments import Instrument
from financial_app.domain.valuation import InstrumentPrice, PriceStatus, instrument_price


def _instrument(currency: str = "PLN", manual_price: str | None = "45.12") -> Instrument:
    price = None if manual_price is None else Decimal(manual_price)
    return Instrument("PZU", 2, currency, "GPW", price, id=1, asset_class_name="Akcje polskie")


def test_a_pln_manual_price_is_its_value_in_pln() -> None:
    price = instrument_price(_instrument(), lambda currency: Decimal(1))

    assert price == InstrumentPrice(Decimal("45.12"), "PLN", Decimal("45.12"), PriceStatus.MANUAL)


def test_a_foreign_manual_price_is_converted_at_the_rate() -> None:
    price = instrument_price(_instrument("USD", "230.50"), {"USD": Decimal("3.6512")}.get)

    assert price == InstrumentPrice(Decimal("230.50"), "USD", Decimal("841.6016"), PriceStatus.MANUAL)


def test_without_a_manual_price_there_is_no_price_and_no_rate_is_looked_up() -> None:
    asked: list[str] = []

    def rate_for(currency: str) -> Decimal | None:
        asked.append(currency)
        return Decimal("3.6512")

    price = instrument_price(_instrument("USD", None), rate_for)

    assert price == InstrumentPrice(None, "USD", None, PriceStatus.NO_PRICE)
    assert asked == []


def test_a_manual_price_without_a_rate_keeps_its_price_but_has_no_pln_value() -> None:
    price = instrument_price(_instrument("USD", "230.50"), lambda currency: None)

    assert price == InstrumentPrice(Decimal("230.50"), "USD", None, PriceStatus.NO_RATE)
