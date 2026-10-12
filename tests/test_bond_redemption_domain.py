"""The net value of a bond (L-4, spec 3.4.1): its gross value less the early-redemption fee (from the built-in fee
table, capped at the accrued interest, none at maturity) and the tax the Account's Tax Regime withholds on the profit of
one bond."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import BELKA_RATE, AccountType, tax_regime_for
from financial_app.domain.bond_redemption import NetValue, early_redemption_fee, net_value
from financial_app.domain.bond_valuation import BondPrice, Cpi, next_anniversary
from financial_app.domain.bonds import BondSeries, BondType, SeriesTerms, add_months, maturity, sale_month
from financial_app.domain.lots import Lot


def _series(name: str, first_rate: str = "0.0535") -> BondSeries:
    rates = (Decimal(first_rate),) + (None,) * 9
    sold = sale_month(name)
    terms = SeriesTerms(name, "PL0", sold, sold, Decimal(100), Decimal("99.9"), Decimal("0.02"), rates, (None,))
    return BondSeries(1, name, terms)


def _lot(day: date, quantity: int = 10, paid: str = "100") -> Lot:
    cost = Decimal(paid) * quantity
    return Lot(day, Decimal(quantity), cost, cost)


def test_a_series_is_sold_in_the_month_its_term_before_maturity() -> None:
    assert sale_month("EDO0536") == date(2026, 5, 1)
    assert sale_month("OTS0118") == date(2017, 10, 1)


def test_adding_months_keeps_the_day_or_takes_the_months_last() -> None:
    assert add_months(date(2026, 5, 22), 120) == date(2036, 5, 22)
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert maturity(BondType.EDO, date(2026, 5, 22)) == date(2036, 5, 22)


def test_the_fee_follows_the_issue_it_applies_from() -> None:
    # MF raised the fees from the September 2024 issues
    assert early_redemption_fee(_series("EDO0834")) == Decimal("2.00")
    assert early_redemption_fee(_series("EDO0934")) == Decimal("3.00")
    assert early_redemption_fee(_series("EDO0536")) == Decimal("3.00")
    assert early_redemption_fee(_series("EDO1014")) == Decimal("2.00")


def test_the_fee_is_capped_at_the_accrued_interest() -> None:
    # 102.04 zł after 139 days at 5.35%: the 3 zł fee takes the 2.04 zł of interest, leaving no profit to tax
    price = BondPrice(_series("EDO0536"), date(2026, 10, 8), Cpi(()))

    value = net_value(price, _lot(date(2026, 5, 22)), BELKA_RATE)

    assert value == NetValue(Decimal("102.04"), Decimal("2.04"), Decimal("0.00"))
    assert value is not None and value.net == Decimal("100.00")


def test_belka_is_withheld_on_the_profit_of_one_bond_after_the_fee() -> None:
    # A year at 6.5%, then 139 days at 5.35%: 108.67 zł; less the 2 zł fee of a pre-September 2024 issue
    series = _series("EDO0534", "0.065")
    series = _with_rates(series, ("0.065", "0.0535"))
    price = BondPrice(series, date(2025, 10, 8), Cpi(()))

    value = net_value(price, _lot(date(2024, 5, 22)), BELKA_RATE)

    assert value is not None
    assert (value.gross, value.fee) == (Decimal("108.67"), Decimal("2.00"))
    # 19% of 6.67 zł is 1.2673 zł, rounded half up to the grosz
    assert value.tax == Decimal("1.27")
    assert value.net == Decimal("105.40")


def test_an_ike_withholds_no_tax_but_still_pays_the_fee() -> None:
    price = BondPrice(_series("EDO0536"), date(2026, 10, 8), Cpi(()))
    rate = tax_regime_for(AccountType.IKE).withheld_tax_rate

    value = net_value(price, _lot(date(2026, 5, 22)), rate)

    assert rate == Decimal(0)
    assert value == NetValue(Decimal("102.04"), Decimal("2.04"), Decimal(0))


def test_bonds_and_regular_accounts_withhold_belka() -> None:
    assert tax_regime_for(AccountType.BONDS).withheld_tax_rate == BELKA_RATE
    assert tax_regime_for(AccountType.REGULAR).withheld_tax_rate == BELKA_RATE
    assert tax_regime_for(AccountType.IKZE).withheld_tax_rate == Decimal(0)


def test_a_rollover_purchase_is_taxed_on_its_discount_too() -> None:
    price = BondPrice(_series("EDO0536"), date(2026, 10, 8), Cpi(()))

    value = net_value(price, _lot(date(2026, 5, 22), paid="99.90"), BELKA_RATE)

    # 102.04 - 2.04 - 99.90 = 0.10 zł of profit, 0.019 zł of tax
    assert value == NetValue(Decimal("102.04"), Decimal("2.04"), Decimal("0.02"))


def test_a_matured_bond_pays_no_fee() -> None:
    series = _series("EDO0536", "0.05")
    series = _with_rates(series, ("0.05",) * 10)
    price = BondPrice(series, date(2036, 6, 1), Cpi(()))

    value = net_value(price, _lot(date(2026, 5, 22)), Decimal(0))

    assert value is not None and value.fee == Decimal(0)


def test_a_series_without_a_value_has_no_net_value() -> None:
    series = BondSeries(1, "COI0530", None)
    price = BondPrice(series, date(2026, 10, 8), Cpi(()))

    assert net_value(price, _lot(date(2026, 5, 22)), BELKA_RATE) is None


def test_the_next_anniversary_is_the_next_period_start_before_maturity() -> None:
    assert next_anniversary(BondType.EDO, date(2026, 5, 22), date(2026, 10, 8)) == date(2027, 5, 22)
    assert next_anniversary(BondType.EDO, date(2026, 5, 22), date(2027, 5, 22)) == date(2028, 5, 22)
    # The last year ends at maturity, which is no anniversary
    assert next_anniversary(BondType.EDO, date(2026, 5, 22), date(2035, 6, 1)) is None


def _with_rates(series: BondSeries, rates: tuple[str, ...]) -> BondSeries:
    assert series.mf is not None
    padded = tuple(Decimal(rate) for rate in rates) + (None,) * (10 - len(rates))
    return replace(series, mf=replace(series.mf, rates=padded))
