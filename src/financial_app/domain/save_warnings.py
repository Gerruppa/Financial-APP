"""What a save of Transactions warns of (#110), whichever place saved them: the transaction dialog, the sheet import,
the XTB Reconciliation or a confirmed bond Draft. Computed from all the Transactions before and after the save, so a
save never needs to say what it changed; it never blocks the save."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_app.domain.account_rules import refusal
from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.contribution_limits import LimitBar, over_limit, over_limit_warning
from financial_app.domain.formatting import format_amount, format_date, format_pln
from financial_app.domain.instruments import Instrument
from financial_app.domain.term_deposits import TermDeposit, locked_capital
from financial_app.domain.transactions import (
    PLN,
    Transaction,
    TransactionDraft,
    TransactionType,
    cash_balances,
    lowest_cash_balance,
)

# The Transactions that put an Instrument into a Position, so a Multi-asset one then needs its split
_BUYING = (TransactionType.BUY, TransactionType.DRIP)


@dataclass(frozen=True)
class CashShortfall:
    """An Account's Cash Balance in ``currency`` going below zero, to ``lowest``, after the save."""

    account_name: str
    currency: str
    lowest: Decimal
    account_id: int

    def message(self, done: str) -> str:
        cash = "Saldo gotówki" if self.currency == PLN else f"Saldo gotówki {self.currency}"
        lowest = format_amount(self.lowest, self.currency)
        return f"{done}, ale {cash} konta {self.account_name} jest ujemne: {lowest}."


@dataclass(frozen=True)
class LockedCash:
    """An Account's PLN cash on ``day`` going below the ``capital`` its running Term Deposits hold (issue #160)."""

    account_name: str
    day: date
    cash: Decimal
    capital: Decimal

    def message(self, done: str) -> str:
        return (
            f"{done}, ale gotówka konta {self.account_name} {format_date(self.day)} ({format_pln(self.cash)}) jest "
            f"mniejsza niż kapitał jej lokat ({format_pln(self.capital)}). Jeśli lokata została zerwana, zaznacz to "
            "w zakładce Dochód stały."
        )


@dataclass(frozen=True)
class NotAllowed:
    """Instruments bought on, or moved into, an Account of a type that may not hold them (``account_rules``). The
    transaction dialog refuses such a Buy; an import or a confirmed Draft only warns, as it enters history."""

    account_name: str
    refusals: tuple[str, ...]

    def message(self) -> str:
        return " ".join(self.refusals)


@dataclass(frozen=True)
class SaveWarnings:
    """What the UI tells the user after a save: the Contribution Limit bars the save has just taken over their limit,
    the negative Cash Balances from the earliest day it touched, the Multi-asset Instruments it bought that have no
    split yet, the Bond Series Instruments it created or removed, the Accounts whose cash it took below the
    capital of their running Term Deposits, and the Instruments it put on an Account that may not hold them."""

    over_limit: tuple[LimitBar, ...] = ()
    negative_cash: tuple[CashShortfall, ...] = ()
    unsplit: tuple[Instrument, ...] = ()
    series_created: tuple[str, ...] = ()
    series_dropped: tuple[str, ...] = ()
    locked_cash: tuple[LockedCash, ...] = ()
    not_allowed: tuple[NotAllowed, ...] = ()

    @property
    def any(self) -> bool:
        return bool(self.over_limit or self.negative_cash or self.unsplit or self.locked_cash or self.not_allowed)

    @property
    def short_of_pln(self) -> tuple[int, ...]:
        """The ids of the Accounts whose PLN cash went below zero: the warning offers their covering Deposits
        (``domain/transactions.py`` ``covering_deposits``, PLN only, #267); a foreign shortfall only warns."""
        return tuple(shortfall.account_id for shortfall in self.negative_cash if shortfall.currency == PLN)

    def messages(self, done: str, *, unsplit: bool = True) -> list[str]:
        """The Polish warnings; ``done`` opens a cash one ("Zapisano", "Usunięto"). Without ``unsplit`` the caller
        asks for the split itself (the transaction dialog opens the split dialog)."""
        texts = [shortfall.message(done) for shortfall in self.negative_cash]
        texts += [locked.message(done) for locked in self.locked_cash]
        texts += [refused.message() for refused in self.not_allowed]
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
    deposits: Sequence[TermDeposit] = (),
) -> SaveWarnings:
    """What the save from ``before`` to ``after`` (all the Transactions, and all the Instruments, either side of it)
    warns of; ``deposits`` are the Term Deposits."""
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
        tuple(_locked_cash(before, after, accounts, changed, deposits)),
        tuple(_not_allowed(after, accounts, changed, instruments)),
    )


def _not_allowed(
    after: Sequence[Transaction],
    accounts: Sequence[Account],
    changed: Iterable[Transaction],
    instruments: Mapping[int, Instrument],
) -> list[NotAllowed]:
    """Why each Account was just bought, or sent, an Instrument it may not hold (``account_rules``); an edit's old
    form or a deletion asks for nothing."""
    saved = set(after)
    by_id = {account.id: account for account in accounts}
    refusals: dict[int, dict[str, None]] = {}
    for t in changed:
        instrument = instruments.get(t.instrument_id) if t.instrument_id is not None else None
        # A Buy or DRIP puts the Instrument on its Account, a Security Transfer on its target
        holder = t.target_account_id if t.transaction_type is TransactionType.SECURITY_TRANSFER else t.account_id
        putting = t.transaction_type in (*_BUYING, TransactionType.SECURITY_TRANSFER)
        if not putting or t not in saved or instrument is None or holder not in by_id:
            continue
        if (why := refusal(by_id[holder], instrument)) is not None:
            refusals.setdefault(holder, {})[why] = None
    return [NotAllowed(by_id[holder].name, tuple(why)) for holder, why in refusals.items()]


def _locked_cash(
    before: Sequence[TransactionDraft],
    after: Sequence[TransactionDraft],
    accounts: Sequence[Account],
    changed: Iterable[TransactionDraft],
    deposits: Sequence[TermDeposit],
) -> list[LockedCash]:
    """Each Account and day a changed Transaction moves PLN cash on, whose cash the save took below the capital of
    the deposits running then; a deposit broken without saying so only warns, like insufficient cash."""
    days = dict.fromkeys(
        (account_id, t.date)
        for t in changed
        for account_id in (t.account_id, t.target_account_id)
        if account_id is not None
    )
    names = {account.id: account.name for account in accounts}
    found = []
    for account_id, day in days:
        capital = locked_capital(deposits, day).get(account_id)
        if capital is None:
            continue
        cash = cash_balances([t for t in after if t.date <= day]).get(account_id, Decimal(0))
        was = cash_balances([t for t in before if t.date <= day]).get(account_id, Decimal(0))
        if cash < capital <= was:
            found.append(LockedCash(names[account_id], day, cash, capital))
    return found


def _negative_cash(
    after: Sequence[TransactionDraft], accounts: Sequence[Account], changed: Iterable[TransactionDraft]
) -> list[CashShortfall]:
    """Insufficient cash only warns (spec 3.3), so history can be entered in any order: each Account and Cash Currency
    a changed Transaction moves, checked from its earliest changed day."""
    starts: dict[tuple[int, str], date] = {}
    for t in changed:
        keys = [(t.account_id, currency) for currency in dict.fromkeys((PLN, t.cash_currency))]
        if t.target_account_id is not None:
            # A Cash Transfer edited or deleted takes its cash back, in its currency (#125)
            keys.append((t.target_account_id, t.cash_currency))
        for key in keys:
            starts[key] = min(t.date, starts.get(key, t.date))
    names = {account.id: account.name for account in accounts}
    shortfalls = []
    for (account_id, currency), start in starts.items():
        lowest = lowest_cash_balance(after, account_id, start=start, currency=currency)
        if lowest < 0:
            shortfalls.append(CashShortfall(names[account_id], currency, lowest, account_id))
    return shortfalls
