"""Account Types, their Tax Regimes and Account validation (spec 3.1)."""

from decimal import Decimal

import pytest

from financial_app.domain.accounts import AccountDraft, AccountError, AccountType, tax_regime_for


@pytest.mark.parametrize("account_type", list(AccountType))
def test_every_account_type_has_a_tax_regime(account_type: AccountType) -> None:
    regime = tax_regime_for(account_type)

    assert regime.name
    assert regime.summary


def test_account_types_are_the_seven_from_the_spec() -> None:
    assert [t.label for t in AccountType] == ["Regular", "IKE", "IKZE", "OIPE", "PPK", "OKI", "Lokata / oszczędności"]


def test_oki_tax_regime_is_a_placeholder_until_the_law_is_final() -> None:
    regime = tax_regime_for(AccountType.OKI)

    assert regime.is_placeholder
    assert "po uchwaleniu przepisów" in regime.summary


@pytest.mark.parametrize("account_type", [t for t in AccountType if t is not AccountType.OKI])
def test_other_tax_regimes_are_not_placeholders(account_type: AccountType) -> None:
    assert not tax_regime_for(account_type).is_placeholder


def test_regular_account_is_taxed_with_belka_in_pit38() -> None:
    assert "19%" in tax_regime_for(AccountType.REGULAR).summary


def _draft(**overrides: object) -> AccountDraft:
    fields: dict[str, object] = {
        "name": "XTB IKE",
        "broker": "XTB",
        "account_type": AccountType.IKE,
        "cash_currencies": ("PLN",),
    }
    fields.update(overrides)
    return AccountDraft(**fields)  # type: ignore[arg-type]


def test_draft_trims_name_and_normalises_currencies() -> None:
    draft = _draft(name="  XTB IKE ", cash_currencies=("pln", " usd", "PLN"))

    assert draft.name == "XTB IKE"
    assert draft.cash_currencies == ("PLN", "USD")


def test_draft_defaults_to_active_without_fx_fee() -> None:
    draft = _draft()

    assert draft.active
    assert draft.fx_conversion_fee_percent is None
    assert not draft.exclude_fx_result


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"name": "   "}, "Nazwa konta"),
        ({"cash_currencies": ()}, "walutę rachunku"),
        ({"cash_currencies": ("PLN", "DOLAR")}, "DOLAR"),
        ({"fx_conversion_fee_percent": Decimal("-0.5")}, "Opłata za przewalutowanie"),
        ({"fx_conversion_fee_percent": Decimal("100")}, "Opłata za przewalutowanie"),
    ],
)
def test_draft_rejects_invalid_fields(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(AccountError, match=message):
        _draft(**overrides)
