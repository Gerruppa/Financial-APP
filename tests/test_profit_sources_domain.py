"""The Dashboard's profit-by-source waterfall (issue #89, spec 5): price effect, FX effect, Dividends, interest,
commissions and costs, and taxes, adding up to the result the Dashboard's tiles show."""

from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import Instrument
from financial_app.domain.profit_sources import ProfitSources, profit_sources
from financial_app.domain.transactions import (
    BrokerConversion,
    TransactionDraft,
    TransactionType,
    buy_or_sell,
    cost,
    currency_exchange,
    dividend,
)

XTB, IKE = 1, 2
PZU, AAPL = 10, 20
USD_4 = NbpRate("USD", Decimal(4), date(2026, 1, 1), "1/A/NBP/2026")
ACCOUNTS = [
    Account("XTB", "", AccountType.REGULAR, ("PLN",), id=XTB),
    Account("IKE", "", AccountType.IKE, ("PLN",), exclude_fx_result=True, id=IKE),
]
INSTRUMENTS = {
    PZU: Instrument("PZU", 1, "PLN", id=PZU, asset_class_name="Akcje", fallback_order=()),
    AAPL: Instrument("Apple", 1, "USD", id=AAPL, asset_class_name="Akcje", fallback_order=()),
}


def _deposit(amount: str, account: int = XTB) -> TransactionDraft:
    return TransactionDraft(account, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(amount))


def _buy_pzu(quantity: str, price: str, fee: str, account: int = XTB) -> TransactionDraft:
    return buy_or_sell(
        account, date(2026, 1, 2), TransactionType.BUY, PZU, Decimal(quantity), Decimal(price), Decimal(fee)
    )


def test_a_pln_position_is_all_price_effect_once_its_commission_counts_as_a_cost() -> None:
    # 10 × 40 zł with a 5 zł commission, now 50 zł: the result is 95 zł
    transactions = [_deposit("1000"), _buy_pzu("10", "40", "5")]

    sources = profit_sources(transactions, ACCOUNTS, INSTRUMENTS, {PZU: Decimal(50)}, {})

    assert sources == ProfitSources(
        price=Decimal(100),
        fx=Decimal(0),
        dividends=Decimal(0),
        interest=Decimal(0),
        costs=Decimal(-5),
        taxes=Decimal(0),
    )
    assert sources.total == Decimal(95)


def test_a_foreign_position_splits_into_price_and_fx_and_the_conversion_fee_is_a_cost() -> None:
    # 10 × 100 USD at the market rate 4 (4000 zł) charged 4020 zł by the broker plus a 5 zł commission;
    # today 120 USD at 5 zł, so 6000 zł against a cost of 4025 zł
    buy = buy_or_sell(
        XTB,
        date(2026, 1, 2),
        TransactionType.BUY,
        AAPL,
        Decimal(10),
        Decimal(100),
        Decimal(5),
        nbp_rate=USD_4,
        conversion=BrokerConversion(Decimal(4020), Decimal("0.5")),
    )

    sources = profit_sources([_deposit("5000"), buy], ACCOUNTS, INSTRUMENTS, {AAPL: Decimal(600)}, {"USD": Decimal(5)})

    assert sources.fx == Decimal(1000)  # 1000 USD worth 1 zł more each
    assert sources.price == Decimal(1000)  # 200 USD more at today's 5 zł
    assert sources.costs == Decimal(-25)
    assert sources.total == Decimal(1975)


def test_dividends_and_interest_count_gross_with_the_withholding_tax_as_a_tax() -> None:
    transactions = [
        _deposit("1000"),
        _buy_pzu("10", "40", "0"),
        dividend(XTB, date(2026, 1, 10), Decimal(100), Decimal(19), instrument_id=PZU),
        dividend(XTB, date(2026, 1, 11), Decimal(10), Decimal("1.90")),
    ]

    sources = profit_sources(transactions, ACCOUNTS, INSTRUMENTS, {PZU: Decimal(40)}, {})

    assert sources.dividends == Decimal(100)
    assert sources.interest == Decimal(10)
    assert sources.taxes == Decimal("-20.90")
    assert sources.price == Decimal(0)
    assert sources.total == Decimal("89.10")


def test_a_foreign_dividend_is_gross_at_the_rate_it_was_paid_at() -> None:
    paid = dividend(XTB, date(2026, 1, 10), Decimal(100), Decimal(15), instrument_id=AAPL, nbp_rate=USD_4)

    sources = profit_sources([paid], ACCOUNTS, INSTRUMENTS, {}, {})

    assert sources.dividends == Decimal(400)
    assert sources.taxes == Decimal(-60)
    assert sources.total == Decimal(340)


def test_costs_count_with_commissions_and_foreign_cash_fx_goes_to_the_fx_effect() -> None:
    transactions = [
        _deposit("1000"),
        cost(XTB, date(2026, 1, 3), Decimal(12)),
        currency_exchange(XTB, date(2026, 1, 3), "USD", Decimal(100), Decimal(400)),
    ]

    sources = profit_sources(transactions, ACCOUNTS, INSTRUMENTS, {}, {"USD": Decimal("4.5")})

    assert sources.costs == Decimal(-12)
    assert sources.fx == Decimal(50)
    assert sources.price == Decimal(0)


def test_an_account_excluding_its_fx_result_leaves_its_foreign_cash_out() -> None:
    transactions = [
        _deposit("1000", IKE),
        currency_exchange(IKE, date(2026, 1, 3), "USD", Decimal(100), Decimal(400)),
    ]

    sources = profit_sources(transactions, ACCOUNTS, INSTRUMENTS, {}, {"USD": Decimal("4.5")})

    assert sources.total == Decimal(0)


def test_the_scope_takes_only_its_accounts() -> None:
    transactions = [_deposit("1000"), _buy_pzu("10", "40", "5"), _deposit("1000", IKE), _buy_pzu("1", "40", "1", IKE)]

    sources = profit_sources(transactions, ACCOUNTS, INSTRUMENTS, {PZU: Decimal(50)}, {}, account_id=IKE)

    assert sources.price == Decimal(10)
    assert sources.costs == Decimal(-1)


def test_after_tax_adds_the_estimated_tax_to_the_taxes() -> None:
    sources = ProfitSources(Decimal(100), Decimal(0), Decimal(0), Decimal(0), Decimal(-5), Decimal(-2))

    assert sources.after_tax(Decimal(19)).taxes == Decimal(-21)
    assert sources.after_tax(Decimal(19)).total == Decimal(74)
