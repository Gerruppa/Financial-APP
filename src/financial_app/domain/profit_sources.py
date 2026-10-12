"""The Dashboard's profit-by-source waterfall (issue #89, spec 5 and 6.1): the View Scope's result since its first
Transaction split into the price effect, the FX effect, Dividends, interest, commissions and costs, and taxes.

The result is the unrealised and realised result of the Positions with the FX result of the foreign cash (unless the
Account excludes it), as ``dashboard`` sums them, plus the net Dividends and interest, less the Costs. Dividends and
interest count gross, their withholding tax under taxes, as does the tax withheld at an Early Redemption;
commissions and FX Conversion Fees count under costs, so the price effect is what the Positions gained before them.
The FX effect comes from ``dashboard`` too: the foreign cash's FX result and, for a foreign Position, how much more (or
less) its cost in the Instrument's currency is worth in PLN today, or was worth at the Sell's rate, than it cost
(``lots.FxBasis``); the price effect is the rest.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from financial_app.domain.transactions import TransactionDraft, TransactionType, costs_by_account


@dataclass(frozen=True)
class ProfitSources:
    """The result by source in PLN; ``costs`` and ``taxes`` are negative or zero."""

    price: Decimal = Decimal(0)
    fx: Decimal = Decimal(0)
    dividends: Decimal = Decimal(0)
    interest: Decimal = Decimal(0)
    costs: Decimal = Decimal(0)
    taxes: Decimal = Decimal(0)

    @property
    def total(self) -> Decimal:
        return self.price + self.fx + self.dividends + self.interest + self.costs + self.taxes

    def after_tax(self, estimated_tax: Decimal) -> ProfitSources:
        """With the ``estimated_tax`` on unrealised gains added to the taxes."""
        return replace(self, taxes=self.taxes - estimated_tax)


def profit_sources(
    transactions: Sequence[TransactionDraft], account_ids: Collection[int], result: Decimal, fx: Decimal
) -> ProfitSources:
    """The result by source of the Accounts ``account_ids`` (the View Scope); ``result`` is their Positions' and
    foreign cash's unrealised and realised result (``Totals.unrealized`` + ``Totals.realized``) and ``fx`` its FX
    part."""
    costs = costs_by_account(transactions)
    spent = sum((costs.get(account, Decimal(0)) for account in account_ids), Decimal(0))
    total = result
    dividends = interest = taxes = Decimal(0)
    for t in (t for t in transactions if t.account_id in account_ids):
        if t.transaction_type is TransactionType.COST:
            total -= t.actual_amount
        elif t.transaction_type is TransactionType.SELL:
            taxes -= t.withholding_tax
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
