"""The Dashboard's profit-by-source waterfall (issue #89, spec 5 and 6.1): the View Scope's result since its first
Transaction split into the price effect, the FX effect, Dividends, interest, commissions and costs, and taxes.

The result is the one the Dashboard's tiles add up to: the unrealised and realised result of the Positions, the FX
result of the foreign cash (unless the Account excludes it), the net Dividends and interest, less the Costs.
Dividends and interest count gross, their withholding tax under taxes; commissions and FX Conversion Fees count
under costs, so the price effect is what the Positions gained before them. A foreign Position's FX effect is how
much more (or less) its cost in the Instrument's currency is worth in PLN today, or was worth at the Sell's rate,
than it cost (``lots.FxBasis``); the price effect is the rest.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from financial_app.domain.accounts import Account
from financial_app.domain.instruments import Instrument
from financial_app.domain.lots import foreign_cash, open_positions, realized_fx_results, realized_results
from financial_app.domain.transactions import TransactionDraft, TransactionType, costs_by_account


@dataclass(frozen=True)
class ProfitSources:
    """The result by source in PLN; ``costs`` and ``taxes`` are negative or zero."""

    price: Decimal
    fx: Decimal
    dividends: Decimal
    interest: Decimal
    costs: Decimal
    taxes: Decimal

    @property
    def total(self) -> Decimal:
        return self.price + self.fx + self.dividends + self.interest + self.costs + self.taxes

    def after_tax(self, estimated_tax: Decimal) -> ProfitSources:
        """With the ``estimated_tax`` on unrealised gains added to the taxes."""
        return replace(self, taxes=self.taxes - estimated_tax)


def profit_sources(
    transactions: Sequence[TransactionDraft],
    accounts: Sequence[Account],
    instruments: Mapping[int, Instrument],
    prices: Mapping[int, Decimal | None],
    rates: Mapping[str, Decimal],
    account_id: int | None = None,
) -> ProfitSources:
    """The result by source of the Account ``account_id`` (``None``: Total), with Positions at ``prices`` (PLN per
    unit by Instrument id) and foreign amounts at ``rates`` (PLN per unit by currency), as in ``dashboard``. A
    Position without a price adds nothing, nor does foreign cash without a rate beyond its realised result."""
    scope = {account.id: account for account in accounts if account_id in (None, account.id)}
    realized = realized_results(transactions)
    realized_fx = realized_fx_results(transactions)
    costs = costs_by_account(transactions)
    total = fx = dividends = interest = taxes = Decimal(0)
    spent = Decimal(0)
    for position in (p for p in open_positions(transactions) if p.account_id in scope):
        price = prices.get(position.instrument_id)
        if price is None:
            continue
        total += position.result(price)
        rate = rates.get(instruments[position.instrument_id].quote_currency)
        if rate is not None:
            fx += position.fx_result(rate)
    for balance in (c for c in foreign_cash(transactions) if c.account_id in scope):
        if scope[balance.account_id].exclude_fx_result:
            continue
        rate = rates.get(balance.currency)
        result = balance.realized_result + (Decimal(0) if rate is None else balance.result(rate))
        total += result
        fx += result
    for account in scope:
        total += realized.get(account, Decimal(0))
        fx += realized_fx.get(account, Decimal(0))
        spent += costs.get(account, Decimal(0))
    for t in (t for t in transactions if t.account_id in scope):
        if t.transaction_type is TransactionType.COST:
            total -= t.actual_amount
        elif t.transaction_type.is_dividend:
            total += t.actual_amount
            gross, withheld = _gross_and_tax(t)
            taxes -= withheld
            if t.instrument_id is None:
                interest += gross
            else:
                dividends += gross
    price_effect = total - fx - dividends - interest + spent - taxes
    return ProfitSources(price_effect, fx, dividends, interest, -spent, taxes)


def _gross_and_tax(t: TransactionDraft) -> tuple[Decimal, Decimal]:
    """A Dividend's gross amount and withholding tax in PLN, at the rate its net amount was paid at (the market rate,
    before the broker's FX Conversion Fee)."""
    assert t.gross is not None  # a Dividend or DRIP, checked on creation
    if t.net:
        rate = t.market_amount / t.net
    else:
        rate = t.fx_rate or (t.nbp_rate.rate if t.nbp_rate else Decimal(1))
    gross = t.gross * rate
    return gross, gross - t.market_amount
