"""An Instrument's price and its status (issue #36, spec 4.1)."""

from datetime import date
from decimal import Decimal

from financial_app.domain.bond_valuation import BondPrice, Cpi
from financial_app.domain.bonds import BondSeries, SeriesTerms
from financial_app.domain.instruments import Instrument
from financial_app.domain.prices import BOSSA, YAHOO, Quote, default_fallback_order
from financial_app.domain.valuation import Badge, InstrumentPrice, PriceStatus, instrument_price


def _instrument(currency: str = "PLN", manual_price: str | None = "45.12") -> Instrument:
    price = None if manual_price is None else Decimal(manual_price)
    return Instrument(
        "PZU",
        2,
        currency,
        "GPW",
        price,
        {"yahoo": "PZU.WA"},
        id=1,
        asset_class_name="Akcje polskie",
        fallback_order=(BOSSA, YAHOO),
    )


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
    return Instrument(
        "PZU",
        2,
        "PLN",
        "GPW",
        None,
        symbols,
        id=1,
        asset_class_name=asset_class,
        fallback_order=default_fallback_order(asset_class),
    )


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


def _bond(manual_price: str | None = None) -> Instrument:
    price = None if manual_price is None else Decimal(manual_price)
    return Instrument(
        "EDO0536", 4, "PLN", "", price, id=1, asset_class_name="Obligacje skarbowe polskie", fallback_order=()
    )


def _bond_price() -> BondPrice:
    terms = SeriesTerms(
        "EDO0536", "PL0", date(2026, 5, 1), date(2026, 5, 31), Decimal(100), None, None, (Decimal("0.0535"),), ()
    )
    return BondPrice(BondSeries(1, "EDO0536", terms), date(2026, 10, 8), Cpi(()))


def test_a_bond_series_is_valued_by_the_mf_issue_letters_without_a_badge() -> None:
    bond_price = _bond_price()

    price = instrument_price(_bond(), None, lambda currency: Decimal(1), bond=bond_price)

    assert price == InstrumentPrice(None, "PLN", bond_price, PriceStatus.BOND, bond=bond_price)


def test_a_manual_price_overrides_the_value_of_a_bond_series() -> None:
    price = instrument_price(_bond("104.5"), None, lambda currency: Decimal(1), bond=_bond_price())

    assert (price.pln, price.status, price.badge) == (Decimal("104.5"), PriceStatus.MANUAL, Badge.MANUAL)


def test_a_bond_series_without_its_first_rate_says_so() -> None:
    price = instrument_price(_bond(), None, lambda currency: Decimal(1))

    assert (price.pln, price.status, price.badge) == (None, PriceStatus.NO_PRICE, Badge.NO_BOND_RATE)


def test_a_bond_not_valued_yet_waits_for_its_slice_of_stage_3() -> None:
    coi = Instrument("COI0530", 4, "PLN", id=1, asset_class_name="Obligacje skarbowe polskie", fallback_order=())

    assert instrument_price(coi, None, lambda currency: Decimal(1)).badge is Badge.STAGE_3


def _metal(grams: str, spread: str | None, manual_price: str | None = None) -> Instrument:
    return Instrument(
        "Złoty Krugerrand 1 oz",
        8,
        "USD",
        "",
        None if manual_price is None else Decimal(manual_price),
        {"yahoo": "GC=F"},
        Decimal(grams),
        None if spread is None else Decimal(spread),
        id=1,
        asset_class_name="Metale i surowce",
        fallback_order=(YAHOO,),
    )


def test_a_one_ounce_coin_with_a_5_percent_spread_is_valued_at_95_percent_of_spot_in_pln() -> None:
    quote = Quote(Decimal(2400), "USD", date(2026, 10, 9), "yahoo")

    price = instrument_price(_metal("31.1034768", "5"), quote, {"USD": Decimal(4)}.get)

    assert (price.price, price.pln) == (Decimal(2280), Decimal(9120))
    assert (price.spot, price.unit_spot_pln) == (Decimal(2400), Decimal(9600))
    assert price.status is PriceStatus.QUOTE


def test_a_coin_of_31_1035_grams_is_worth_95_percent_of_spot() -> None:
    quote = Quote(Decimal(2400), "USD", date(2026, 10, 9), "yahoo")

    price = instrument_price(_metal("31.1035", "5"), quote, {"USD": Decimal(4)}.get)

    assert isinstance(price.pln, Decimal)
    assert abs(price.pln - Decimal(9120)) < Decimal("0.1")


def test_a_metal_manual_price_is_the_spot_per_troy_ounce() -> None:
    price = instrument_price(_metal("31.1034768", "5", manual_price="2000"), None, {"USD": Decimal(4)}.get)

    assert (price.price, price.pln, price.spot) == (Decimal(1900), Decimal(7600), Decimal(2000))


def test_a_metal_without_a_rate_has_its_unit_price_but_no_pln_value() -> None:
    quote = Quote(Decimal(2400), "USD", date(2026, 10, 9), "yahoo")

    price = instrument_price(_metal("31.1034768", None), quote, lambda currency: None)

    assert (price.price, price.pln, price.spot, price.unit_spot_pln) == (Decimal(2400), None, Decimal(2400), None)


def test_an_instrument_without_a_metal_weight_has_no_spot() -> None:
    quote = Quote(Decimal("45.12"), "PLN", date(2026, 10, 9), "yahoo")

    price = instrument_price(_automatic(), quote, lambda currency: Decimal(1))

    assert (price.spot, price.unit_spot_pln) == (None, None)
