"""Which Instruments an Account may buy: each Account Type is for some products only (a Bonds Account for retail
treasury bonds, an Other one for coins and crypto). The rule is on the Account Type and the Instrument's Type, so it
changes no calculation; the transaction dialog refuses a Buy against it and a save by an import only warns."""

from enum import StrEnum

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.instruments import CRYPTO_CLASS, Instrument, InstrumentType


class Product(StrEnum):
    """What an Instrument is, for the rule only. Listed in the order the Polish lists name them."""

    RETAIL_BOND = "retail_bond"
    SECURITY = "security"
    FUND = "fund"
    CRYPTO = "crypto"
    METAL = "metal"
    OTHER = "other"


# What each Product is called in a list ("można kupić: ...") and after "nie przyjmuje"
_LISTED = {
    Product.RETAIL_BOND: "obligacje skarbowe detaliczne",
    Product.SECURITY: "akcje, ETF, ETC i obligacje giełdowe",
    Product.FUND: "fundusze",
    Product.CRYPTO: "kryptowaluty",
    Product.METAL: "metale fizyczne",
    Product.OTHER: "instrumenty typu Inne",
}
_REFUSED = {
    Product.RETAIL_BOND: "obligacji skarbowych detalicznych",
    Product.SECURITY: "akcji, ETF, ETC i obligacji giełdowych",
    Product.FUND: "funduszy",
    Product.CRYPTO: "kryptowalut",
    Product.METAL: "metali fizycznych",
    Product.OTHER: "instrumentów typu Inne",
}

_BROKERAGE = (Product.SECURITY, Product.FUND)
# IKE, IKZE and OIPE hold retail bonds too (spec 3.1: "Bonds held on an IKE stay on an IKE Account")
_RETIREMENT = (Product.RETAIL_BOND, *_BROKERAGE, Product.OTHER)
_ALLOWED = {
    AccountType.REGULAR: (*_BROKERAGE, Product.CRYPTO, Product.OTHER),
    AccountType.IKE: _RETIREMENT,
    AccountType.IKZE: _RETIREMENT,
    AccountType.OIPE: _RETIREMENT,
    AccountType.OKI: (*_BROKERAGE, Product.OTHER),
    AccountType.PPK: (Product.FUND,),
    AccountType.BONDS: (Product.RETAIL_BOND,),
    # Term Deposits are their own tab, not Instruments
    AccountType.DEPOSIT: (),
    AccountType.OTHER: (Product.CRYPTO, Product.METAL, Product.OTHER),
}

_SECURITY_TYPES = (
    InstrumentType.STOCK,
    InstrumentType.ETF,
    InstrumentType.ETC,
    InstrumentType.TREASURY_BOND,
    InstrumentType.BOND,
)


def product_of(instrument: Instrument) -> Product:
    """The Product of ``instrument``: a Bond Series first, a physical metal (by weight or Type) or crypto, then the
    Instrument Type; one the user left as Inne is Other."""
    if instrument.is_bond_series:
        return Product.RETAIL_BOND
    if instrument.metal_grams is not None or instrument.instrument_type is InstrumentType.METAL:
        return Product.METAL
    if instrument.instrument_type is InstrumentType.CRYPTO or instrument.asset_class_name == CRYPTO_CLASS:
        return Product.CRYPTO
    if instrument.instrument_type is InstrumentType.FUND:
        return Product.FUND
    if instrument.instrument_type in _SECURITY_TYPES:
        return Product.SECURITY
    return Product.OTHER


def allowed_products(account_type: AccountType) -> tuple[Product, ...]:
    """The Products an Account of ``account_type`` may buy, in list order."""
    return _ALLOWED[account_type]


def products_text(account_type: AccountType) -> str:
    """What an Account of ``account_type`` may buy, in Polish, for a list or a message."""
    allowed = allowed_products(account_type)
    return ", ".join(_LISTED[product] for product in allowed) if allowed else "nic (lokaty są w zakładce Dochód stały)"


def can_hold(account_type: AccountType, instrument: Instrument) -> bool:
    return product_of(instrument) in _ALLOWED[account_type]


def refusal(account: Account, instrument: Instrument) -> str | None:
    """Why ``account`` may not buy ``instrument``, in Polish, or ``None`` when it may."""
    if can_hold(account.account_type, instrument):
        return None
    product = product_of(instrument)
    text = (
        f"Konto {account.name} typu {account.account_type.label} nie przyjmuje {_REFUSED[product]} ({instrument.name})."
    )
    if product is Product.RETAIL_BOND:
        text += f" Załóż do nich konto typu {AccountType.BONDS.label} lub kup je na koncie IKE albo IKZE."
    if not allowed_products(account.account_type):
        return f"{text} Na tym koncie nie kupuje się instrumentów. Lokaty dodaj w zakładce Dochód stały."
    return f"{text} Na tym koncie można kupić: {products_text(account.account_type)}."
