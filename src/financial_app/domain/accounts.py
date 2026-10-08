"""Accounts, Account Types and the Tax Regime each type maps to (spec 3.1)."""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class AccountError(ValueError):
    """An Account field the user must correct; the message is shown in the UI (Polish)."""


class AccountType(StrEnum):
    """The legal wrapper of an Account. Values are stored in the database, so never rename them."""

    REGULAR = "regular"
    IKE = "ike"
    IKZE = "ikze"
    OIPE = "oipe"
    PPK = "ppk"
    OKI = "oki"
    DEPOSIT = "deposit"

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    AccountType.REGULAR: "Regular",
    AccountType.IKE: "IKE",
    AccountType.IKZE: "IKZE",
    AccountType.OIPE: "OIPE",
    AccountType.PPK: "PPK",
    AccountType.OKI: "OKI",
    AccountType.DEPOSIT: "Lokata / oszczędności",
}


@dataclass(frozen=True)
class TaxRegime:
    """How gains on an Account are taxed. Tax calculations hang off this module as later stages add them."""

    name: str
    summary: str
    is_placeholder: bool = False


_TAX_REGIMES = {
    AccountType.REGULAR: TaxRegime("Podatek Belki", "19% podatku od zysku przy każdej sprzedaży, rozliczany w PIT-38."),
    AccountType.IKE: TaxRegime(
        "IKE", "Zwolnienie z podatku przy wypłacie spełniającej warunki ustawy; w przeciwnym razie podatek od zysku."
    ),
    AccountType.IKZE: TaxRegime(
        "IKZE", "Wpłaty odliczane od dochodu; przy wypłacie zryczałtowany podatek 10% od całej kwoty."
    ),
    AccountType.OIPE: TaxRegime(
        "OIPE", "Jak IKE: zwolnienie przy wypłacie spełniającej warunki, w przeciwnym razie podatek od zysku."
    ),
    AccountType.PPK: TaxRegime("PPK", "Zasady opodatkowania właściwe dla PPK."),
    AccountType.OKI: TaxRegime(
        "OKI",
        "Zasady opodatkowania OKI zostaną dodane po uchwaleniu przepisów.",
        is_placeholder=True,
    ),
    AccountType.DEPOSIT: TaxRegime("Podatek Belki od odsetek", "19% podatku od odsetek, pobierany przez bank."),
}


def tax_regime_for(account_type: AccountType) -> TaxRegime:
    return _TAX_REGIMES[account_type]


_CURRENCY_CODE = re.compile(r"[A-Z]{3}")
_MAX_FEE_PERCENT = Decimal(100)


@dataclass(frozen=True)
class AccountDraft:
    """The user-editable fields of an Account, validated and normalised on creation."""

    name: str
    broker: str
    account_type: AccountType
    cash_currencies: tuple[str, ...]
    fx_conversion_fee_percent: Decimal | None = None
    exclude_fx_result: bool = False
    active: bool = True

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise AccountError("Nazwa konta nie może być pusta.")
        currencies = tuple(dict.fromkeys(code.strip().upper() for code in self.cash_currencies))
        if not currencies:
            raise AccountError("Podaj co najmniej jedną walutę rachunku.")
        for code in currencies:
            if not _CURRENCY_CODE.fullmatch(code):
                raise AccountError(f"Nieprawidłowy kod waluty: {code}. Użyj trzyliterowego kodu, np. PLN.")
        fee = self.fx_conversion_fee_percent
        if fee is not None and not (0 <= fee < _MAX_FEE_PERCENT):
            raise AccountError("Opłata za przewalutowanie musi wynosić co najmniej 0% i mniej niż 100%.")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "broker", self.broker.strip())
        object.__setattr__(self, "cash_currencies", currencies)


@dataclass(frozen=True)
class Account(AccountDraft):
    """A saved Account."""

    id: int = field(kw_only=True)
