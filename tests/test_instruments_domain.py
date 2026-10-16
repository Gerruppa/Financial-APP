"""Instrument and Asset Class validation (spec 3.2)."""

from decimal import Decimal

import pytest

from financial_app.domain.instruments import (
    DistributionPolicy,
    InstrumentDraft,
    InstrumentError,
    validate_asset_class_name,
)


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


def test_isin_is_optional_trimmed_and_upper_cased() -> None:
    assert _draft().isin == ""
    assert _draft(isin=" ie00b6r52259 ").isin == "IE00B6R52259"


@pytest.mark.parametrize("isin", ["IE00B6R5225", "IE00B6R522599", "1E00B6R52259", "IE00B6R5225X", "IE00-6R52259"])
def test_malformed_isin_is_rejected(isin: str) -> None:
    with pytest.raises(InstrumentError, match="ISIN"):
        _draft(isin=isin)


def test_fund_details_are_optional() -> None:
    draft = _draft()

    assert (draft.ter_percent, draft.distribution_policy, draft.domicile) == (None, None, "")


def test_fund_details_keep_ter_policy_and_trimmed_domicile() -> None:
    draft = _draft(
        ter_percent=Decimal("0.07"), distribution_policy=DistributionPolicy.ACCUMULATING, domicile="  Irlandia "
    )

    assert (draft.ter_percent, draft.distribution_policy, draft.domicile) == (
        Decimal("0.07"),
        DistributionPolicy.ACCUMULATING,
        "Irlandia",
    )


@pytest.mark.parametrize("ter", [Decimal("-0.01"), Decimal(100), Decimal(250)])
def test_ter_is_at_least_zero_and_below_100(ter: Decimal) -> None:
    with pytest.raises(InstrumentError, match="TER"):
        _draft(ter_percent=ter)


def test_distribution_policies_have_polish_labels() -> None:
    assert [policy.label for policy in DistributionPolicy] == ["Akumulacja", "Dystrybucja"]


def test_a_stored_distribution_policy_value_becomes_the_policy() -> None:
    assert _draft(distribution_policy="distributing").distribution_policy is DistributionPolicy.DISTRIBUTING


def test_quantity_decimals_default_to_whole_units_and_go_up_to_eight() -> None:
    assert InstrumentDraft("CD Projekt", 1, "PLN").quantity_decimals == 0
    assert InstrumentDraft("Bitcoin", 1, "USD", quantity_decimals=8).quantity_decimals == 8


@pytest.mark.parametrize("decimals", [-1, 9])
def test_quantity_decimals_outside_zero_to_eight_are_rejected(decimals: int) -> None:
    with pytest.raises(InstrumentError, match="od 0 do 8"):
        InstrumentDraft("Bitcoin", 1, "USD", quantity_decimals=decimals)
