"""What a save of Transactions warns of (#110), whichever place saved them: the transaction dialog, the sheet import,
the XTB Reconciliation or a confirmed bond Draft. Computed from all the Transactions before and after the save, so a
save never needs to say what it changed; it never blocks the save."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.contribution_limits import LimitBar, over_limit, over_limit_warning
from financial_app.domain.formatting import format_amount
from financial_app.domain.instruments import Instrument
from financial_app.domain.transactions import PLN, Transaction, TransactionDraft, TransactionType, lowest_cash_balance

# The Transactions that put an Instrument into a Position, so a Multi-asset one then needs its split
_BUYING = (TransactionType.BUY, TransactionType.DRIP)


@dataclass(frozen=True)
class CashShortfall:
    """An Account's Cash Balance in ``currency`` going below zero, to ``lowest``, after the save."""

    account_name: str
    currency: str
    lowest: Decimal

    def message(self, done: str) -> str:
        cash = "Saldo gotówki" if self.currency == PLN else f"Saldo gotówki {self.currency}"
        lowest = format_amount(self.lowest, self.currency)
        return f"{done}, ale {cash} konta {self.account_name} jest ujemne: {lowest}."


@dataclass(frozen=True)
class SaveWarnings:
    """What the UI tells the user after a save: the Contribution Limit bars the save has just taken over their limit,
    the negative Cash Balances from the earliest day it touched, the Multi-asset Instruments it bought that have no
    split yet, and the Bond Series Instruments it created or removed."""

    over_limit: tuple[LimitBar, ...] = ()
    negative_cash: tuple[CashShortfall, ...] = ()
    unsplit: tuple[Instrument, ...] = ()
    series_created: tuple[str, ...] = ()
    series_dropped: tuple[str, ...] = ()

    @property
    def any(self) -> bool:
        return bool(self.over_limit or self.negative_cash or self.unsplit)

    def messages(self, done: str, *, unsplit: bool = True) -> list[str]:
        """The Polish warnings; ``done`` opens a cash one ("Zapisano", "Usunięto"). Without ``unsplit`` the caller
        asks for the split itself (the transaction dialog opens the split dialog)."""
        texts = [shortfall.message(done) for shortfall in self.negative_cash]
        texts += [over_limit_warning(bar) for bar in self.over_limit]
        if unsplit and self.unsplit:
            names = ", ".join(instrument.name for instrument in self.unsplit)
            texts.append(f"Instrumenty Multi-asset bez podziału na klasy: {names}. Podaj go w zakładce Multi-asset.")
        return texts


def touched(before: Iterable[Transaction], after: Iterable[Transaction]) -> list[Transaction]:
    """The Transactions a save changed: the new form of each added or changed one, then the old form of each changed
    or removed one."""
    old = {transaction.id: transaction for transaction in before}
    new = {transaction.id: transaction for transaction in after}
    added = [transaction for i, transaction in new.items() if old.get(i) != transaction]
    removed = [transaction for i, transaction in old.items() if new.get(i) != transaction]
    return added + removed


def save_warnings(
    before: Sequence[Transaction],
    after: Sequence[Transaction],
    accounts: Iterable[Account],
    instruments_before: Iterable[Instrument],
    instruments_after: Iterable[Instrument],
    limits: Mapping[int, Mapping[AccountType, Decimal | None]],
) -> SaveWarnings:
    """What the save from ``before`` to ``after`` (all the Transactions, and all the Instruments, either side of it)
    warns of."""
    accounts = list(accounts)
    changed = touched(before, after)
    saved = set(after)
    instruments = {instrument.id: instrument for instrument in instruments_after}
    # Only what the save bought, in the form it now has: an edit's old form or a deletion asks for no split
    bought = dict.fromkeys(t.instrument_id for t in changed if t in saved and t.transaction_type in _BUYING)
    unsplit = [
        instrument
        for i in bought
        if i is not None
        and (instrument := instruments.get(i)) is not None
        and instrument.is_multi_asset
        and not instrument.multi_asset_split
    ]
    series_before = {i.name for i in instruments_before if i.is_bond_series}
    series_after = {i.name for i in instruments.values() if i.is_bond_series}
    return SaveWarnings(
        tuple(over_limit(before, after, accounts, limits, changed)),
        tuple(_negative_cash(after, accounts, changed)),
        tuple(unsplit),
        tuple(sorted(series_after - series_before)),
        tuple(sorted(series_before - series_after)),
    )


def _negative_cash(
    after: Sequence[TransactionDraft], accounts: Sequence[Account], changed: Iterable[TransactionDraft]
) -> list[CashShortfall]:
    """Insufficient cash only warns (spec 3.3), so history can be entered in any order: each Account and Cash Currency
    a changed Transaction moves, checked from its earliest changed day."""
    starts: dict[tuple[int, str], date] = {}
    for t in changed:
        keys = [(t.account_id, currency) for currency in dict.fromkeys((PLN, t.cash_currency))]
        if t.target_account_id is not None:
            keys.append((t.target_account_id, PLN))  # a Cash Transfer edited or deleted takes its cash back
        for key in keys:
            starts[key] = min(t.date, starts.get(key, t.date))
    names = {account.id: account.name for account in accounts}
    shortfalls = []
    for (account_id, currency), start in starts.items():
        lowest = lowest_cash_balance(after, account_id, start=start, currency=currency)
        if lowest < 0:
            shortfalls.append(CashShortfall(names[account_id], currency, lowest))
    return shortfalls
