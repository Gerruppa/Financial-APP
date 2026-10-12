"""Investment Strategies (issue #76, spec 5): Allocation Targets per Asset Class with tolerance bands, Instrument
Targets within a class, and the Planned Deposit split toward them without selling ("water-filling").

Total has one Investment Strategy and each Account may have its own. Targets are percent (of the View Scope's value
for an Asset Class, of the class for an Instrument); shares are fractions, as in ``domain.dashboard``.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import Enum

from financial_app.domain.instruments import AssetClass, Instrument

DEFAULT_BAND = Decimal(5)


class BandStatus(Enum):
    """Where a class stands against its tolerance band: within it, up to twice it away, or further."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class StrategyError(ValueError):
    """An Investment Strategy field the user must correct; the message is shown in the UI (Polish)."""


@dataclass(frozen=True)
class ClassTarget:
    """An Allocation Target: ``percent`` of the View Scope's value, kept within ±``band`` percentage points."""

    percent: Decimal
    band: Decimal = DEFAULT_BAND

    def __post_init__(self) -> None:
        _check_percent(self.percent, "Cel klasy")
        _check_percent(self.band, "Pasmo tolerancji")


@dataclass(frozen=True)
class Strategy:
    """The Investment Strategy of the Account ``account_id`` (``None``: Total): the Allocation Targets by Asset Class
    id and the Instrument Targets (percent of the Instrument's class) by Instrument id."""

    account_id: int | None
    class_targets: Mapping[int, ClassTarget] = field(default_factory=dict)
    instrument_targets: Mapping[int, Decimal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for percent in self.instrument_targets.values():
            _check_percent(percent, "Cel w klasie")

    @property
    def is_empty(self) -> bool:
        return not self.class_targets and not self.instrument_targets


def _check_percent(percent: Decimal, field_name: str) -> None:
    if not 0 <= percent <= 100:
        raise StrategyError(f"{field_name} musi wynosić od 0 do 100%.")


@dataclass(frozen=True)
class InstrumentRow:
    """An Instrument held in an Asset Class or named by an Instrument Target: its PLN ``value`` in the class, its
    ``share`` of the class, its ``target`` (percent of the class) and its part of the Planned Deposit (``None`` without
    a strategy or while the class's Instrument Targets do not sum to 100%)."""

    instrument: Instrument
    value: Decimal
    share: Decimal
    target: Decimal | None = None
    from_deposit: Decimal | None = None


@dataclass(frozen=True)
class ClassRow:
    """An Asset Class of the View Scope: its PLN ``value`` and ``share`` today, and with a ``target`` the
    ``difference`` from it in percentage points and the PLN ``to_target`` that buying (positive) or selling (negative)
    would bring it to its target. ``from_deposit`` is its part of the Planned Deposit (``None`` without a strategy),
    split further across its ``instruments``."""

    asset_class: str
    value: Decimal
    share: Decimal
    target: ClassTarget | None = None
    difference: Decimal | None = None
    to_target: Decimal | None = None
    from_deposit: Decimal | None = None
    instruments: tuple[InstrumentRow, ...] = ()
    instrument_targets_sum: Decimal | None = None

    @property
    def status(self) -> BandStatus | None:
        if self.target is None or self.difference is None:
            return None
        if abs(self.difference) <= self.target.band:
            return BandStatus.GREEN
        return BandStatus.YELLOW if abs(self.difference) <= 2 * self.target.band else BandStatus.RED

    @property
    def split_blocked(self) -> bool:
        """Whether Instrument Targets that do not sum to 100% keep the class's part of the deposit unsplit."""
        return self.instrument_targets_sum is not None and self.instrument_targets_sum != 100


@dataclass(frozen=True)
class StrategyView:
    """The View Scope's Asset Classes held or targeted, in the order of the Asset Class list, and the deposit that
    would bring every class to its target without selling (``None`` without a strategy or when a class without a
    target holds value, so that only selling reaches the targets)."""

    rows: tuple[ClassRow, ...]
    rebalancing_deposit: Decimal | None = None
    targets_sum: Decimal | None = None


def strategy_view(
    strategy: Strategy | None,
    asset_classes: Sequence[AssetClass],
    instruments: Mapping[int, Instrument],
    classes: Mapping[str, Decimal],
    holdings: Mapping[str, Mapping[int, Decimal]],
    planned: Decimal = Decimal(0),
) -> StrategyView:
    """The View Scope's ``classes`` (PLN value by Asset Class name, cash included, as the Dashboard's allocation)
    against ``strategy`` (``None``: only the structure); ``holdings`` is the value by class name and Instrument id.
    The ``planned`` deposit is split across the targeted classes, then their Instruments, without selling."""
    names = {asset_class.id: asset_class.name for asset_class in asset_classes}
    targets = {} if strategy is None else strategy.class_targets
    by_name = {names[class_id]: target for class_id, target in targets.items() if class_id in names}
    shown = [name for name in names.values() if classes.get(name) or name in by_name]
    shown += [name for name, value in classes.items() if name not in shown and value]
    values = {name: classes.get(name, Decimal(0)) for name in shown}
    total = sum(values.values(), Decimal(0))
    weights = {name: target.percent for name, target in by_name.items()}
    deposits = None if strategy is None else water_fill(values, weights, planned)
    instrument_targets: dict[str, dict[int, Decimal]] = {}
    for instrument_id, percent in ({} if strategy is None else strategy.instrument_targets).items():
        if instrument_id in instruments:
            instrument_targets.setdefault(instruments[instrument_id].asset_class_name, {})[instrument_id] = percent
    rows = []
    for name in shown:
        value = values[name]
        target = by_name.get(name)
        from_deposit = None if deposits is None else deposits.get(name, Decimal(0))
        row = ClassRow(name, value, value / total if total else Decimal(0), target, from_deposit=from_deposit)
        if target is not None:
            row = replace(
                row, difference=row.share * 100 - target.percent, to_target=target.percent * total / 100 - value
            )
        rows.append(_with_instruments(row, instruments, holdings.get(name, {}), instrument_targets.get(name)))
    if strategy is None:
        return StrategyView(tuple(rows))
    return StrategyView(tuple(rows), rebalancing_deposit(values, weights), sum(weights.values(), Decimal(0)))


def _with_instruments(
    row: ClassRow,
    instruments: Mapping[int, Instrument],
    held: Mapping[int, Decimal],
    targets: Mapping[int, Decimal] | None,
) -> ClassRow:
    """``row`` with a row per Instrument held in it or targeted, largest first, and the class's part of the deposit
    split across them: toward their targets, else in proportion to their values.

    A Multi-asset Instrument with a Multi-asset Split counts in the class's value but gets no row: buying it would
    also add to its other classes, which a split without selling must not overshoot."""
    held = {i: value for i, value in held.items() if not instruments[i].multi_asset_split}
    values = {instrument_id: held.get(instrument_id, Decimal(0)) for instrument_id in {*held, *(targets or {})}}
    targets_sum = None if targets is None else sum(targets.values(), Decimal(0))
    deposits: dict[int, Decimal] | None = None
    if row.from_deposit is not None and (targets_sum is None or targets_sum == 100):
        deposits = water_fill(values, values if targets is None else targets, row.from_deposit)
    rows = [
        InstrumentRow(
            instruments[instrument_id],
            value,
            value / row.value if row.value else Decimal(0),
            None if targets is None else targets.get(instrument_id),
            None if deposits is None else deposits.get(instrument_id, Decimal(0)),
        )
        for instrument_id, value in values.items()
    ]
    rows.sort(key=lambda r: (-r.value, r.instrument.name.casefold()))
    return replace(row, instruments=tuple(rows), instrument_targets_sum=targets_sum)


def water_fill[K](values: Mapping[K, Decimal], weights: Mapping[K, Decimal], amount: Decimal) -> dict[K, Decimal]:
    """``amount`` split without selling across the keys with a positive weight, toward the value shares that their
    weights set: the key furthest below its share (value per weight) is filled first, until it reaches the next one,
    then both together, and so on. Keys without a positive weight get nothing."""
    targeted = sorted((key for key, weight in weights.items() if weight > 0), key=lambda k: _ratio(values, weights, k))
    if not targeted or amount <= 0:
        return {}
    value_sum = weight_sum = Decimal(0)
    level = Decimal(0)
    for index, key in enumerate(targeted):
        value_sum += values.get(key, Decimal(0))
        weight_sum += weights[key]
        # The value per weight that the keys filled so far reach together
        level = (amount + value_sum) / weight_sum
        if index + 1 == len(targeted) or level <= _ratio(values, weights, targeted[index + 1]):
            break
    return {key: max(weights[key] * level - values.get(key, Decimal(0)), Decimal(0)) for key in targeted}


def rebalancing_deposit[K](values: Mapping[K, Decimal], weights: Mapping[K, Decimal]) -> Decimal | None:
    """The deposit that brings every key to the value share its weight sets without selling, ``None`` when there are
    no weights or a key without a positive weight holds value."""
    targeted = [key for key, weight in weights.items() if weight > 0]
    if not targeted or any(value and weights.get(key, Decimal(0)) <= 0 for key, value in values.items()):
        return None
    weight_sum = sum((weights[key] for key in targeted), Decimal(0))
    # The total at which the most over-target key is exactly on target
    needed = max(_ratio(values, weights, key) for key in targeted) * weight_sum
    return max(needed - sum(values.values(), Decimal(0)), Decimal(0))


def _ratio[K](values: Mapping[K, Decimal], weights: Mapping[K, Decimal], key: K) -> Decimal:
    return values.get(key, Decimal(0)) / weights[key]


def deposit_accounts(
    view: StrategyView,
    asset_classes: Sequence[AssetClass],
    strategies: Mapping[int, Strategy],
    account_classes: Mapping[int, Mapping[str, Decimal]],
) -> dict[str, tuple[int, ...]]:
    """For Total's Planned Deposit: the Accounts each class receiving a part of it could be bought on, by id, those
    whose own strategy targets the class first, then those holding it, largest holding first (spec 5, Q66).

    ``strategies`` are the Accounts' own Investment Strategies and ``account_classes`` each Account's value by Asset
    Class name."""
    names = {asset_class.id: asset_class.name for asset_class in asset_classes}
    suggested = {}
    for row in view.rows:
        if not row.from_deposit:
            continue
        targeted = [
            account_id
            for account_id, strategy in strategies.items()
            if any(names.get(i) == row.asset_class and t.percent > 0 for i, t in strategy.class_targets.items())
        ]
        holders = sorted(
            (a for a, classes in account_classes.items() if classes.get(row.asset_class) and a not in targeted),
            key=lambda a: account_classes[a][row.asset_class],
            reverse=True,
        )
        suggested[row.asset_class] = (*targeted, *holders)
    return suggested
