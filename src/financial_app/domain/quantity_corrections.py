"""Quantity corrections (#278): a Sell or Security Transfer needing more units than its Account held is offered a
correcting Transaction instead of only being refused, for the small real differences a crypto exchange leaves (a fee
taken in the coin, rounding in an export, dust after a conversion).

The FIFO engine tolerates nothing (ADR-0003): quantities stay exact and every correction is a visible Transaction the
user confirms. A shortfall is fixed by a Buy of the missing units on the Sell's day, at cost 0 (the cost of the units
held carries the fee) or at the Sell's own price, or by trimming the Sell (or Transfer) to what the Account held. A
Buy at cost 0 is an ordinary Buy at price 0 (``TransactionDraft.costs_nothing``), so nothing new is stored.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from financial_app.domain.formatting import format_amount, format_pln, format_quantity
from financial_app.domain.lots import InsufficientQuantityError, replay
from financial_app.domain.transactions import (
    GROSZ,
    PLN,
    Origin,
    Transaction,
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
)

# The comment of a correcting Buy, so the user can find it in the Transakcje list
CORRECTION_COMMENT = "Korekta ilości: brakujące jednostki do sprzedaży lub transferu"
# Above this share of the Sell's quantity a missing Buy or transfer is more likely than a fee: nothing is preselected
LARGE_GAP = Decimal("0.01")
# The key of a draft that is neither saved nor imported: the one the transaction dialog saves
NEW = "new"
# The decimals of a trimmed Sell's price, which keeps its amount over fewer units
_PRICE = Decimal("1E-8")


class Fix(StrEnum):
    """How a shortfall is corrected."""

    FREE_BUY = "free_buy"
    PRICED_BUY = "priced_buy"
    TRIM = "trim"

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    Fix.FREE_BUY: "Dodaj brakujące jednostki po 0 zł",
    Fix.PRICED_BUY: "Dodaj brakujące jednostki po cenie sprzedaży",
    Fix.TRIM: "Zmniejsz liczbę do tego, co było na koncie",
}


def shortfall_key(t: TransactionDraft) -> str:
    """What names an uncovered Transaction across redraws: its import id, its saved id, or ``NEW``."""
    if t.external_id is not None:
        return t.external_id
    return f"#{t.id}" if isinstance(t, Transaction) else NEW


@dataclass(frozen=True)
class Shortfall:
    """The Sell or Security Transfer ``uncovered`` needing more units than the ``held`` ones, which cost
    ``held_cost``; ``fix`` is the one chosen, or by default the Buy at cost 0 for a gap within ``LARGE_GAP``, else
    ``None``. Unless ``trimmable``, it is only topped up (an import adds, it does not edit a saved Transaction)."""

    uncovered: TransactionDraft
    held: Decimal
    held_cost: Decimal
    fix: Fix | None
    trimmable: bool = True

    @property
    def key(self) -> str:
        return shortfall_key(self.uncovered)

    @property
    def quantity(self) -> Decimal:
        assert self.uncovered.quantity is not None  # a Sell or Security Transfer
        return self.uncovered.quantity

    @property
    def gap(self) -> Decimal:
        """The units missing."""
        return self.quantity - self.held

    @property
    def large(self) -> bool:
        """More than ``LARGE_GAP`` of the quantity: more likely a missing Buy or transfer than a fee."""
        return self.gap > self.quantity * LARGE_GAP

    @property
    def is_sell(self) -> bool:
        return self.uncovered.transaction_type is TransactionType.SELL

    @property
    def value(self) -> Decimal | None:
        """The missing units' approximate PLN value: what the Sell got for them, or for a transfer what the units held
        cost each; ``None`` for a transfer of nothing held."""
        if self.is_sell:
            return _pln(self.uncovered.actual_amount * self.gap / self.quantity)
        return _pln(self.held_cost * self.gap / self.held) if self.held else None

    @property
    def fixes(self) -> tuple[Fix, ...]:
        """The fixes on offer: a priced Buy only for a Sell whose missing units are worth a grosz, a trim only when
        something was held."""
        offered = [Fix.FREE_BUY]
        if self._priced_buy() is not None:
            offered.append(Fix.PRICED_BUY)
        if self.held and self.trimmable:
            offered.append(Fix.TRIM)
        return tuple(offered)

    def correction(self, fix: Fix) -> tuple[TransactionDraft | None, TransactionDraft | None]:
        """What ``fix`` saves: the Buy it adds, and what replaces ``uncovered`` (the trimmed Transaction)."""
        if fix is Fix.TRIM:
            return None, self._trimmed()
        buy = self._priced_buy() if fix is Fix.PRICED_BUY else self._free_buy()
        assert buy is not None  # offered in ``fixes``
        return buy, None

    def effect(self, fix: Fix) -> str:
        """What ``fix`` changes in cost and realised result, in Polish."""
        gap = f"{format_quantity(self.gap)} szt."
        if not self.is_sell:
            if fix is Fix.TRIM:
                return (
                    f"Transfer {format_quantity(self.held)} szt. zamiast {format_quantity(self.quantity)} szt.: "
                    f"na konto docelowe trafi to, co było na koncie, o koszcie {format_pln(self.held_cost)}."
                )
            return (
                f"Zakup {gap} po 0 zł w dniu transferu: na konto docelowe trafi {format_quantity(self.quantity)} szt. "
                f"o koszcie {format_pln(self.held_cost)}."
            )
        result = self.uncovered.actual_amount - self.held_cost
        if fix is Fix.PRICED_BUY:
            buy = self._priced_buy()
            assert buy is not None
            cost = self.held_cost + buy.actual_amount
            return (
                f"Zakup {gap} po cenie sprzedaży za {format_pln(buy.actual_amount)} z gotówki; koszt sprzedanych "
                f"jednostek: {format_pln(cost)}, wynik ze sprzedaży: {format_pln(result - buy.actual_amount)}."
            )
        outcome = f"koszt sprzedanych jednostek: {format_pln(self.held_cost)}, wynik ze sprzedaży: {format_pln(result)}"
        if fix is Fix.TRIM:
            trimmed = self._trimmed()
            assert trimmed.price is not None and self.uncovered.price is not None
            currency = PLN if self.uncovered.nbp_rate is None else self.uncovered.nbp_rate.currency
            return (
                f"Sprzedaż {format_quantity(self.held)} szt. zamiast {format_quantity(self.quantity)} szt. za tę samą "
                f"kwotę, po {format_amount(trimmed.price, currency)} zamiast "
                f"{format_amount(self.uncovered.price, currency)} za szt.; {outcome}."
            )
        return f"Zakup {gap} po 0 zł w dniu sprzedaży; {outcome}."

    def _free_buy(self) -> TransactionDraft:
        t = self.uncovered
        assert t.instrument_id is not None
        free = buy_or_sell(t.account_id, t.date, TransactionType.BUY, t.instrument_id, self.gap, Decimal(0))
        return self._marked(free)

    def _priced_buy(self) -> TransactionDraft | None:
        """The Buy of the missing units at the Sell's price and rates; ``None`` for a transfer, or when they are worth
        less than a grosz."""
        t = self.uncovered
        if not self.is_sell or t.price is None or t.instrument_id is None:
            return None
        try:
            buy = buy_or_sell(
                t.account_id,
                t.date,
                TransactionType.BUY,
                t.instrument_id,
                self.gap,
                t.price,
                fx_rate=t.fx_rate,
                nbp_rate=t.nbp_rate,
                cash_currency=t.cash_currency,
            )
        except TransactionError:
            return None
        return self._marked(buy)

    def _marked(self, buy: TransactionDraft) -> TransactionDraft:
        """The correcting Buy, commented; an imported one's is imported too, under its id with "-correction"."""
        t = self.uncovered
        buy = replace(buy, comment=CORRECTION_COMMENT)
        if t.origin is Origin.BROKER and t.external_id is not None:
            return replace(buy, origin=Origin.BROKER, external_id=f"{t.external_id}-correction")
        return buy

    def _trimmed(self) -> TransactionDraft:
        """``uncovered`` with the units held; a Sell keeps its amount, so its price rises."""
        t = self.uncovered
        if not self.is_sell:
            return replace(t, quantity=self.held)
        assert t.price is not None
        price = (self.quantity * t.price / self.held).quantize(_PRICE, rounding=ROUND_HALF_UP)
        return replace(t, quantity=self.held, price=price)


def quantity_shortfalls(
    transactions: Sequence[TransactionDraft], fixes: Mapping[str, Fix] | None = None, *, trim_saved: bool = True
) -> list[Shortfall]:
    """Every Sell or Security Transfer of ``transactions`` (in entry order) that takes more units FIFO than its
    Account held, by date: each found with the earlier ones fixed as chosen in ``fixes`` (by ``shortfall_key``),
    since a trimmed transfer brings its target fewer units. One with no fix chosen counts as topped up at cost 0 to
    look further. Without ``trim_saved`` a saved Transaction is only topped up. A Sell naming its Lot, or any other
    error of the replay, ends the search: saving still refuses it."""
    chosen = fixes or {}
    current = list(transactions)
    found: list[Shortfall] = []
    for _ in range(len(current) + 1):
        try:
            replay(current)
            break
        except InsufficientQuantityError as error:
            uncovered = error.transaction
            if uncovered is None:
                break
            key = shortfall_key(uncovered)
            trimmable = trim_saved or not isinstance(uncovered, Transaction)
            shortfall = Shortfall(uncovered, error.held, error.held_cost, None, trimmable)
            fix = chosen.get(key)
            if fix not in shortfall.fixes:
                fix = None if shortfall.large else Fix.FREE_BUY
            found.append(replace(shortfall, fix=fix))
            # By identity: the drafts of a dialog's save share the key NEW
            buy, trimmed = shortfall.correction(fix or Fix.FREE_BUY)
            current = [trimmed if trimmed is not None and t is uncovered else t for t in current]
            current.extend([] if buy is None else [buy])
        except TransactionError:
            break
    return found


def chosen_corrections(shortfalls: Sequence[Shortfall]) -> tuple[dict[str, TransactionDraft], list[TransactionDraft]]:
    """What the fixed ``shortfalls`` save: the trimmed Transactions by the ``shortfall_key`` of the one each
    replaces, and the correcting Buys."""
    trimmed: dict[str, TransactionDraft] = {}
    added: list[TransactionDraft] = []
    for shortfall in shortfalls:
        if shortfall.fix is None:
            continue
        buy, replacement = shortfall.correction(shortfall.fix)
        if replacement is not None:
            trimmed[shortfall.key] = replacement
        if buy is not None:
            added.append(buy)
    return trimmed, added


def _pln(value: Decimal) -> Decimal:
    return value.quantize(GROSZ, rounding=ROUND_HALF_UP)
