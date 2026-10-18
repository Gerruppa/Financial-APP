"""The window's change events (issue #112): the shell publishes what changed, and each tab or header element redraws
on the changes it declared it depends on."""

from collections.abc import Callable, Iterable
from enum import Enum, auto
from typing import Protocol


class Change(Enum):
    TRANSACTIONS = auto()  # a Transaction saved, edited or deleted
    PRICES = auto()  # a price refresh
    BOND_DATA = auto()  # the MF file, GUS CPI or the NBP reference rate fetched
    SCOPE = auto()  # the View Scope switched
    HISTORY = auto()  # History outdated or computed
    INSTRUMENTS = auto()  # an Instrument's Asset Class or Multi-asset Split changed
    RECURRING_RULES = auto()  # a Recurring Rule or its skipped occurrences changed


# What a tab valuing the View Scope's holdings today redraws on
TODAYS_VALUE = frozenset({Change.TRANSACTIONS, Change.PRICES, Change.BOND_DATA, Change.SCOPE})


class Redrawing(Protocol):
    """A tab or section that declares the changes it redraws on."""

    @property
    def CHANGES(self) -> frozenset[Change]: ...  # noqa: N802 - a constant on the tab's class

    def refresh(self) -> None: ...


class ChangeEvents:
    """One window's subscribers. A publish redraws each subscriber of any published change once, in subscription
    order; a change published by a subscriber meanwhile joins that publish."""

    def __init__(self) -> None:
        self._subscribers: list[tuple[Callable[[], object], frozenset[Change]]] = []
        self._published: set[Change] = set()
        self._publishing = False

    def subscribe(self, redraw: Callable[[], object], changes: Iterable[Change]) -> None:
        self._subscribers.append((redraw, frozenset(changes)))

    def publish(self, *changes: Change) -> None:
        self._published.update(changes)
        if self._publishing:
            return
        self._publishing = True
        redrawn: set[int] = set()
        try:
            # Another pass while a subscriber published a change an earlier one depends on
            while due := [
                index
                for index, (_, wanted) in enumerate(self._subscribers)
                if index not in redrawn and wanted & self._published
            ]:
                for index in due:
                    redrawn.add(index)
                    self._subscribers[index][0]()
        finally:
            self._published.clear()
            self._publishing = False
