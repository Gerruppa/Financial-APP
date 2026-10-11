"""Instrument and Asset Class validation (spec 3.2)."""

from decimal import Decimal

import pytest

from financial_app.domain.instruments import InstrumentDraft, InstrumentError, validate_asset_class_name


def _draft(**overrides: object) -> InstrumentDraft:
    fields: dict[str, object] = {
        "name": "PZU",
        "asset_class_id": 2,
        "quote_currency": "PLN",
        "market": "GPW",
        "manual_price": Decimal("45.12"),
    }
    fields.update(overrides)
    return InstrumentDraft(**fields)  # type: ignore[arg-type]


def test_draft_trims_text_and_upper_cases_the_currency() -> None:
    draft = _draft(name="  PZU ", quote_currency=" usd ", market=" NYSE ")

    assert (draft.name, draft.quote_currency, draft.market) == ("PZU", "USD", "NYSE")


def test_market_and_manual_price_are_optional() -> None:
    draft = _draft(market="", manual_price=None)

    assert draft.market == ""
    assert draft.manual_price is None


def test_empty_name_is_rejected() -> None:
    with pytest.raises(InstrumentError, match="Nazwa instrumentu"):
        _draft(name="   ")


@pytest.mark.parametrize("code", ["", "US", "USDX", "U$D"])
def test_invalid_quote_currency_is_rejected(code: str) -> None:
    with pytest.raises(InstrumentError, match="waluty"):
        _draft(quote_currency=code)


@pytest.mark.parametrize("price", [Decimal(0), Decimal("-1")])
def test_manual_price_must_be_positive(price: Decimal) -> None:
    with pytest.raises(InstrumentError, match="Cena ręczna"):
        _draft(manual_price=price)


def test_asset_class_name_is_trimmed() -> None:
    assert validate_asset_class_name("  Akcje polskie ") == "Akcje polskie"


def test_empty_asset_class_name_is_rejected() -> None:
    with pytest.raises(InstrumentError, match="Nazwa klasy"):
        validate_asset_class_name(" ")


def test_a_physical_metal_has_its_weight_in_grams_and_buyback_spread() -> None:
    draft = _draft(metal_grams=Decimal("31.1034768"), buyback_spread_percent=Decimal(5))

    assert (draft.metal_grams, draft.buyback_spread_percent) == (Decimal("31.1034768"), Decimal(5))


@pytest.mark.parametrize("grams", [Decimal(0), Decimal(-1)])
def test_metal_weight_must_be_positive(grams: Decimal) -> None:
    with pytest.raises(InstrumentError, match="Waga metalu"):
        _draft(metal_grams=grams)


@pytest.mark.parametrize("spread", [Decimal(-1), Decimal(100)])
def test_buyback_spread_is_at_least_zero_and_below_100(spread: Decimal) -> None:
    with pytest.raises(InstrumentError, match="Spread odkupu"):
        _draft(metal_grams=Decimal(1), buyback_spread_percent=spread)


def test_a_buyback_spread_needs_a_metal_weight() -> None:
    with pytest.raises(InstrumentError, match="wagi metalu"):
        _draft(buyback_spread_percent=Decimal(5))


def test_a_metal_unit_is_worth_the_spot_per_troy_ounce_for_its_weight_less_the_spread() -> None:
    coin = _draft(metal_grams=Decimal("31.1034768"), buyback_spread_percent=Decimal(5))
    bar = _draft(metal_grams=Decimal("15.5517384"))

    assert coin.unit_price(Decimal(2400)) == Decimal(2280)
    assert bar.unit_price(Decimal(2400)) == Decimal(1200)


def test_without_a_metal_weight_the_price_is_the_unit_price() -> None:
    assert _draft().unit_price(Decimal("45.12")) == Decimal("45.12")
