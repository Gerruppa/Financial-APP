"""Which Instruments an Account Type may buy."""

import pytest

from financial_app.domain.account_rules import Product, allowed_products, can_hold, product_of, refusal
from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.instruments import Instrument, InstrumentType


def _instrument(
    name: str,
    instrument_type: InstrumentType = InstrumentType.OTHER,
    asset_class: str = "Akcje polskie",
    metal_grams: int | None = None,
) -> Instrument:
    return Instrument(
        name, 1, "PLN", instrument_type=instrument_type, metal_grams=metal_grams,  # type: ignore[arg-type]
        id=1, asset_class_name=asset_class, fallback_order=(),
    )  # fmt: skip


EDO = _instrument("EDO0336", InstrumentType.TREASURY_BOND, "Obligacje skarbowe polskie")
CATALYST_BOND = _instrument("DS1030", InstrumentType.TREASURY_BOND, "Obligacje skarbowe polskie")
ETF = _instrument("VWCE", InstrumentType.ETF, "Akcje zagraniczne")
STOCK = _instrument("CD Projekt", InstrumentType.STOCK)
FUND = _instrument("PKO Akcji", InstrumentType.FUND)
BITCOIN = _instrument("Bitcoin", InstrumentType.CRYPTO, "Kryptowaluty")
GOLD_COIN = _instrument("Filharmonik", InstrumentType.METAL, "Metale i surowce", metal_grams=31)
GOLD_ETC = _instrument("Gold ETC", InstrumentType.ETC, "Metale i surowce")
UNTYPED = _instrument("Coś")


def test_every_instrument_has_one_product() -> None:
    assert product_of(EDO) is Product.RETAIL_BOND
    assert product_of(CATALYST_BOND) is Product.SECURITY  # DS or IZ on Catalyst is not a Bond Series
    assert product_of(ETF) is Product.SECURITY
    assert product_of(GOLD_ETC) is Product.SECURITY  # a paper gold is a security, unlike a coin
    assert product_of(FUND) is Product.FUND
    assert product_of(BITCOIN) is Product.CRYPTO
    assert product_of(GOLD_COIN) is Product.METAL
    assert product_of(UNTYPED) is Product.OTHER


@pytest.mark.parametrize(
    ("account_type", "held"),
    [
        (AccountType.BONDS, [EDO]),
        (AccountType.REGULAR, [ETF, STOCK, FUND, CATALYST_BOND, GOLD_ETC, BITCOIN, UNTYPED]),
        (AccountType.IKE, [EDO, ETF, STOCK, FUND, CATALYST_BOND, GOLD_ETC, UNTYPED]),
        (AccountType.IKZE, [EDO, ETF, STOCK, FUND, CATALYST_BOND, GOLD_ETC, UNTYPED]),
        (AccountType.OIPE, [EDO, ETF, STOCK, FUND, CATALYST_BOND, GOLD_ETC, UNTYPED]),
        (AccountType.OKI, [ETF, STOCK, FUND, CATALYST_BOND, GOLD_ETC, UNTYPED]),
        (AccountType.PPK, [FUND]),
        (AccountType.OTHER, [GOLD_COIN, BITCOIN, UNTYPED]),
        (AccountType.DEPOSIT, []),
    ],
)
def test_an_account_type_holds_only_what_it_is_for(account_type: AccountType, held: list[Instrument]) -> None:
    everything = [EDO, CATALYST_BOND, ETF, STOCK, FUND, BITCOIN, GOLD_COIN, GOLD_ETC, UNTYPED]

    assert [i.name for i in everything if can_hold(account_type, i)] == [i.name for i in everything if i in held]


def test_a_regular_account_refuses_retail_bonds_and_points_to_the_bonds_account() -> None:
    account = Account("XTB", "XTB", AccountType.REGULAR, ("PLN",), id=1)

    assert refusal(account, EDO) == (
        "Konto XTB typu Regular nie przyjmuje obligacji skarbowych detalicznych (EDO0336). "
        "Załóż do nich konto typu Obligacje lub kup je na koncie IKE albo IKZE. "
        "Na tym koncie można kupić: akcje, ETF, ETC i obligacje giełdowe, fundusze, kryptowaluty, "
        "instrumenty typu Inne."
    )
    assert refusal(account, ETF) is None


def test_a_bonds_account_refuses_gold_and_says_what_it_takes() -> None:
    account = Account("PKO obligacje", "PKO", AccountType.BONDS, ("PLN",), id=2)

    message = refusal(account, GOLD_COIN)

    assert message is not None
    assert message.startswith("Konto PKO obligacje typu Obligacje nie przyjmuje metali fizycznych (Filharmonik).")
    assert message.endswith("Na tym koncie można kupić: obligacje skarbowe detaliczne.")


def test_a_deposit_account_buys_no_instruments_and_points_to_the_term_deposits() -> None:
    account = Account("Lokaty", "", AccountType.DEPOSIT, ("PLN",), id=3)

    assert allowed_products(AccountType.DEPOSIT) == ()
    assert refusal(account, ETF) == (
        "Konto Lokaty typu Lokata / oszczędności nie przyjmuje akcji, ETF, ETC i obligacji giełdowych (VWCE). "
        "Na tym koncie nie kupuje się instrumentów. Lokaty dodaj w zakładce Dochód stały."
    )
