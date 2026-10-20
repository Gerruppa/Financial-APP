"""The Portfolio's grouping of an Account's Positions (issue #198): none, by Instrument Type or by Asset Class, each
group with its value and its share of the Account's value. Only a view: it changes no value.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from financial_app.domain.instruments import Instrument, InstrumentType
from financial_app.domain.lots import Position, UnitPrice


class Grouping(StrEnum):
    """The Portfolio's "Grupuj" choice; values are stored in the settings, so never rename them."""

    NONE = "none"
    INSTRUMENT_TYPE = "instrument_type"
    ASSET_CLASS = "asset_class"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @classmethod
    def parse(cls, text: str | None) -> Grouping:
        """The saved choice; none saved, or one no longer known, is no grouping."""
        return cls(text) if text in {grouping.value for grouping in cls} else cls.NONE


_LABELS = {
    Grouping.NONE: "brak",
    Grouping.INSTRUMENT_TYPE: "Rodzaj instrumentu",
    Grouping.ASSET_CLASS: "Klasa aktywów",
}


@dataclass(frozen=True)
class PositionGroup:
    """The Positions of one group in the order given, their value in PLN (a Position without a price at cost, as in
    the Account's value) and their ``share`` of the Account's value in percent, ``None`` when that is zero."""

    title: str
    positions: list[Position]
    value: Decimal
    share: Decimal | None


def group_positions(
    positions: Sequence[Position],
    instruments: Mapping[int, Instrument],
    prices: Mapping[int, UnitPrice | None],
    grouping: Grouping,
    account_value: Decimal,
) -> list[PositionGroup]:
    """The groups of ``positions`` (one, titled "", without grouping): by Instrument Type in the list's order, or by
    Asset Class name; ``prices`` are PLN per unit by Instrument id."""
    groups: dict[str, list[Position]] = {}
    if grouping is Grouping.INSTRUMENT_TYPE:
        order = list(InstrumentType)
        ranked = sorted(positions, key=lambda p: order.index(instruments[p.instrument_id].instrument_type))
        for position in ranked:
            groups.setdefault(instruments[position.instrument_id].instrument_type.label, []).append(position)
    elif grouping is Grouping.ASSET_CLASS:
        ranked = sorted(positions, key=lambda p: instruments[p.instrument_id].asset_class_name.casefold())
        for position in ranked:
            groups.setdefault(instruments[position.instrument_id].asset_class_name, []).append(position)
    else:
        groups[""] = list(positions)
    result = []
    for title, members in groups.items():
        value = sum((p.value_or_cost(prices.get(p.instrument_id)) for p in members), Decimal(0))
        share = value / account_value * 100 if account_value else None
        result.append(PositionGroup(title, members, value, share))
    return result
