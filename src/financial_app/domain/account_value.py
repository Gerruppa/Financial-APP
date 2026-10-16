"""An Account's value and result today (issue #109): the one definition the Portfolio's cards and the Dashboard's
Account rows share.

A Position without a PLN price counts at cost and adds nothing to the result; foreign cash without an NBP Rate counts
at cost and adds only its realised FX result. The FX result of foreign cash counts in the result unless the Account
excludes it (spec 3.1, 3.5).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from financial_app.domain.accounts import Account
from financial_app.domain.lots import ForeignCash, Position, UnitPrice


@dataclass(frozen=True)
class AccountValue:
    """In PLN: the PLN Cash Balance ``cash``; ``open_positions``, the Positions and the foreign cash; ``unrealized``,
    the Positions' result at their prices plus the foreign cash's unrealised FX result; ``realized_fx``, the FX result
    of the foreign cash already spent (both FX parts nothing when the Account excludes them); ``fx``, the foreign cash's
    whole FX result, shown even when excluded; ``holds``, whether the Account holds cash, a Position or foreign cash."""

    cash: Decimal
    open_positions: Decimal
    unrealized: Decimal
    realized_fx: Decimal
    fx: Decimal
    holds: bool

    @property
    def value(self) -> Decimal:
        return self.cash + self.open_positions

    @property
    def result(self) -> Decimal:
        """The result the Portfolio's card shows: unrealised, plus the realised FX result of foreign cash."""
        return self.unrealized + self.realized_fx


def account_value(
    account: Account,
    cash: Decimal,
    positions: Iterable[Position],
    foreign: Iterable[ForeignCash],
    prices: Mapping[int, UnitPrice | None],
    rates: Mapping[str, Decimal],
) -> AccountValue:
    """The value of ``account`` holding ``cash`` PLN and its own of ``positions`` (at ``prices``, PLN per unit by
    Instrument id) and ``foreign`` cash (at ``rates``, PLN per unit by currency)."""
    open_positions = unrealized = realized_fx = fx = Decimal(0)
    holds = bool(cash)
    for position in (p for p in positions if p.account_id == account.id):
        holds = True
        price = prices.get(position.instrument_id)
        open_positions += position.value_or_cost(price)
        if price is not None:
            unrealized += position.result(price)
    for balance in (c for c in foreign if c.account_id == account.id):
        holds = holds or bool(balance.lots)
        rate = rates.get(balance.currency)
        open_positions += balance.cost if rate is None else balance.value(rate)
        unrealised_fx = Decimal(0) if rate is None else balance.result(rate)
        fx += balance.realized_result + unrealised_fx
        if not account.exclude_fx_result:
            realized_fx += balance.realized_result
            unrealized += unrealised_fx
    return AccountValue(cash, open_positions, unrealized, realized_fx, fx, holds)


def is_listed(account: Account, value: AccountValue) -> bool:
    """Whether the Account shows among the Accounts: an inactive one stays hidden unless it still holds something."""
    return account.active or value.holds
