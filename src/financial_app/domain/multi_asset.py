"""The Multi-asset tab (issue #75, spec 5): the Multi-asset Instruments held and their value in each Asset Class."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from financial_app.domain.instruments import Instrument
from financial_app.domain.lots import Position, UnitPrice


@dataclass(frozen=True)
class MultiAssetHolding:
    """A Multi-asset Instrument held in the View Scope: its PLN ``value`` today (at cost when ``priced`` is false) and
    that value by Asset Class, as its Multi-asset Split spreads it (whole in its own class without one)."""

    instrument: Instrument
    value: Decimal
    priced: bool
    parts: tuple[tuple[str, Decimal], ...]


def multi_asset_holdings(
    positions: Sequence[Position],
    instruments: Mapping[int, Instrument],
    prices: Mapping[int, UnitPrice | None],
    account_id: int | None,
) -> list[MultiAssetHolding]:
    """The Multi-asset Instruments among ``positions`` of the Account ``account_id`` (``None``: every Account), valued
    at ``prices`` (PLN per unit by Instrument id), largest first."""
    values: dict[int, Decimal] = {}
    for position in positions:
        if account_id not in (None, position.account_id) or not instruments[position.instrument_id].is_multi_asset:
            continue
        value = position.value_or_cost(prices.get(position.instrument_id))
        values[position.instrument_id] = values.get(position.instrument_id, Decimal(0)) + value
    holdings = [
        MultiAssetHolding(instruments[i], value, prices.get(i) is not None, tuple(instruments[i].class_parts(value)))
        for i, value in values.items()
    ]
    return sorted(holdings, key=lambda holding: holding.value, reverse=True)
