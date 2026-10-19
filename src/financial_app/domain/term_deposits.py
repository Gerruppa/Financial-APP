"""Term Deposits (issue #160): a Deposit Account's contract tying part of its cash up for a term at an annual rate.

Its interest is worked out per capitalisation period: the capital at the period's start × the annual rate × the
period's actual days / 365, rounded to the grosz, with Belka withheld by the bank on each period (also rounded to the
grosz). A period capitalised before maturity adds its net interest to the next period's capital.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from financial_app.domain.accounts import Account, tax_regime_for
from financial_app.domain.bonds import add_months
from financial_app.domain.transactions import TransactionDraft, TransactionType, dividend

GROSZ = Decimal("0.01")
DAYS_A_YEAR = 365
# How far from a period's end interest entered by hand or imported may lie and still pay it
MATCH_WINDOW = timedelta(days=7)


class TermDepositError(ValueError):
    """A Term Deposit's fields do not make one; the message is for the user, in Polish."""


class Capitalization(StrEnum):
    """How often the bank capitalises the interest. Values are stored, so never rename them."""

    AT_MATURITY = "at_maturity"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"
    YEARLY = "yearly"

    @property
    def months(self) -> int | None:
        """The months between two capitalisations; ``None`` for once, at maturity."""
        return {"at_maturity": None, "monthly": 1, "quarterly": 3, "semiannual": 6, "yearly": 12}[self.value]


class TermUnit(StrEnum):
    """The unit of a Term Deposit's term. Values are stored, so never rename them."""

    MONTHS = "months"
    DAYS = "days"


@dataclass(frozen=True)
class TermDepositDraft:
    """A Term Deposit's fields: ``principal`` PLN on the Account from ``start_date`` for ``term_count`` months or days
    at ``annual_rate`` percent a year, its interest capitalised as ``capitalization`` says. ``renew`` makes "Odnów" the
    maturity Draft's default; ``closed_on`` is the day it ended (on maturity, or earlier when broken)."""

    account_id: int
    name: str
    principal: Decimal
    start_date: date
    term_count: int
    term_unit: TermUnit
    annual_rate: Decimal
    capitalization: Capitalization
    renew: bool = False
    closed_on: date | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise TermDepositError("Podaj nazwę lokaty.")
        if not self.principal > 0:
            raise TermDepositError("Kwota lokaty musi być większa od zera.")
        if self.principal != self.principal.quantize(GROSZ):
            raise TermDepositError("Kwotę lokaty podaj z dokładnością do grosza.")
        if not self.term_count > 0:
            raise TermDepositError("Okres lokaty musi być większy od zera.")
        if not self.annual_rate > 0:
            raise TermDepositError("Oprocentowanie musi być większe od zera.")
        if self.closed_on is not None and self.closed_on < self.start_date:
            raise TermDepositError("Data zakończenia nie może być przed założeniem lokaty.")
        if self.closed_on is not None and self.closed_on > self.maturity:
            raise TermDepositError("Data zakończenia nie może być po terminie zapadalności.")

    @property
    def maturity(self) -> date:
        if self.term_unit is TermUnit.MONTHS:
            return add_months(self.start_date, self.term_count)
        return self.start_date + timedelta(days=self.term_count)


@dataclass(frozen=True)
class TermDeposit(TermDepositDraft):
    """A saved Term Deposit."""

    id: int = field(kw_only=True)


@dataclass(frozen=True)
class InterestPeriod:
    """The ``number``-th capitalisation period, from ``start`` to ``end``, of ``capital``, paying ``gross`` interest
    less the ``tax`` withheld."""

    number: int
    start: date
    end: date
    capital: Decimal
    gross: Decimal
    tax: Decimal

    @property
    def net(self) -> Decimal:
        return self.gross - self.tax


def interest_periods(deposit: TermDepositDraft, tax_rate: Decimal) -> list[InterestPeriod]:
    """The Term Deposit's capitalisation periods, the earliest first; ``tax_rate`` is the Belka the bank withholds.

    A period ends every ``capitalization`` months counted from the start (the month's last day when shorter), the
    last one on maturity. A deposit broken before maturity (``closed_on``) forfeits the period it was broken in."""
    periods: list[InterestPeriod] = []
    capital = deposit.principal
    for number, (start, end) in enumerate(_period_days(deposit), start=1):
        gross = _round(capital * deposit.annual_rate / 100 * (end - start).days / DAYS_A_YEAR)
        tax = _round(gross * tax_rate)
        periods.append(InterestPeriod(number, start, end, capital, gross, tax))
        capital += gross - tax
    return periods


def _period_days(deposit: TermDepositDraft) -> list[tuple[date, date]]:
    """The first and last day of each period paying interest: those ended by the day a broken deposit closed."""
    maturity = deposit.maturity
    step = deposit.capitalization.months
    ends: list[date] = []
    if step is not None:
        count = 1
        while (end := add_months(deposit.start_date, count * step)) < maturity:
            ends.append(end)
            count += 1
    ends.append(maturity)
    closed = deposit.closed_on or maturity
    return [(start, end) for start, end in zip([deposit.start_date, *ends], ends, strict=False) if end <= closed]


@dataclass(frozen=True)
class AccruedInterest:
    """Interest earned and not in the cash yet: ``gross`` less the ``tax`` the bank will withhold."""

    gross: Decimal = Decimal(0)
    tax: Decimal = Decimal(0)

    @property
    def net(self) -> Decimal:
        return self.gross - self.tax

    def __add__(self, other: AccruedInterest) -> AccruedInterest:
        return AccruedInterest(self.gross + other.gross, self.tax + other.tax)


# A Term Deposit's period: (its id, the period's last day)
type PeriodKey = tuple[int, date]


def paid_periods(deposits: Iterable[TermDeposit], transactions: Iterable[TransactionDraft]) -> dict[PeriodKey, date]:
    """The day each period of ``deposits`` was paid, by the period: by interest linked to it (whatever its day), else
    by interest entered by hand or imported (no Instrument, no link) on the deposit's Account within ``MATCH_WINDOW``
    of the period's end. The periods of every deposit, oldest first, each take the nearest such interest still free,
    so one pays one period; amounts are never compared."""
    interest = [
        t
        for t in transactions
        if t.transaction_type is TransactionType.DIVIDEND and t.instrument_id is None and t.lot_id is None
    ]
    paid: dict[PeriodKey, date] = {}
    for t in interest:
        if t.term_deposit_id is not None and t.term_deposit_period is not None:
            paid[(t.term_deposit_id, t.term_deposit_period)] = t.date
    free = [t for t in interest if t.term_deposit_id is None]
    pending = sorted(
        (end, deposit.id, deposit.account_id)
        for deposit in deposits
        for _, end in _period_days(deposit)
        if (deposit.id, end) not in paid
    )
    for end, deposit_id, account_id in pending:
        candidates = [t for t in free if t.account_id == account_id and abs(t.date - end) <= MATCH_WINDOW]
        if candidates:
            found = min(candidates, key=lambda t: (abs(t.date - end), t.date))
            free.remove(found)
            paid[(deposit_id, end)] = found.date
    return paid


def accrued_interest(
    deposit: TermDeposit, tax_rate: Decimal, day: date, paid: Mapping[PeriodKey, date]
) -> AccruedInterest:
    """The deposit's interest earned by the end of ``day`` and not paid into the cash by then: each period ended and
    not paid yet in full, and the running period's days so far (gross and tax each rounded to the grosz)."""
    return _accrued(deposit, interest_periods(deposit, tax_rate), tax_rate, day, paid)


def _accrued(
    deposit: TermDeposit,
    periods: Iterable[InterestPeriod],
    tax_rate: Decimal,
    day: date,
    paid: Mapping[PeriodKey, date],
) -> AccruedInterest:
    accrued = AccruedInterest()
    for period in periods:
        paid_on = paid.get((deposit.id, period.end))
        # Interest paid by the day is in the cash, even when entered a few days before its period ended
        if period.start >= day or (paid_on is not None and paid_on <= day):
            continue
        if period.end <= day:
            accrued += AccruedInterest(period.gross, period.tax)
            continue
        gross = _round(period.capital * deposit.annual_rate / 100 * (day - period.start).days / DAYS_A_YEAR)
        accrued += AccruedInterest(gross, _round(gross * tax_rate))
    return accrued


def _round(amount: Decimal) -> Decimal:
    return amount.quantize(GROSZ, ROUND_HALF_UP)


@dataclass(frozen=True)
class InterestDraft:
    """A ``period`` of a ``deposit`` on ``account`` ended and not paid yet: confirmed as its interest."""

    deposit: TermDeposit
    account: Account
    period: InterestPeriod

    @property
    def due(self) -> date:
        return self.period.end

    def transaction(self) -> TransactionDraft:
        """The interest Dividend (no Instrument) paying the period into the Account's PLN cash, linked to it."""
        paid = dividend(
            self.account.id,
            self.period.end,
            self.period.gross,
            self.period.tax,
            f"Odsetki {self.deposit.name} · okres {self.period.number}",
        )
        return replace(paid, term_deposit_id=self.deposit.id, term_deposit_period=self.period.end)


@dataclass(frozen=True)
class DepositMaturityDraft:
    """A ``deposit`` on ``account`` past its maturity and not closed yet: ended there, or renewed from that day.
    ``final_capital`` is what it pays back: the principal and every period's net interest."""

    deposit: TermDeposit
    account: Account
    final_capital: Decimal

    @property
    def due(self) -> date:
        return self.deposit.maturity

    def renewal(self, annual_rate: Decimal) -> TermDepositDraft:
        """The same deposit again from its maturity, of its whole capital, at ``annual_rate``."""
        same = {f.name: getattr(self.deposit, f.name) for f in fields(TermDepositDraft)}
        return TermDepositDraft(
            **same | {"principal": self.final_capital, "start_date": self.due, "annual_rate": annual_rate}
        )


# A Draft of either kind: each has its ``due`` day
type DepositDraft = InterestDraft | DepositMaturityDraft


def deposit_drafts(
    deposits: Iterable[TermDeposit],
    accounts: Sequence[Account],
    transactions: Iterable[TransactionDraft],
    day: date,
    account_id: int | None,
) -> list[DepositDraft]:
    """The Drafts due by ``day`` in the View Scope (``account_id``, ``None`` for Total), the earliest first (on one
    day, the interest before the maturity): the periods ended and not paid, and the deposits matured and not
    closed."""
    by_id = {account.id: account for account in accounts}
    deposits = list(deposits)
    paid = paid_periods(deposits, transactions)
    deposits = [d for d in deposits if account_id in (None, d.account_id)]
    drafts: list[DepositDraft] = []
    for deposit in deposits:
        account = by_id[deposit.account_id]
        periods = interest_periods(deposit, tax_rate_of(account))
        drafts.extend(
            InterestDraft(deposit, account, period)
            for period in periods
            if period.end <= day and (deposit.id, period.end) not in paid
        )
        if deposit.closed_on is None and deposit.maturity <= day:
            final = deposit.principal + sum((period.net for period in periods), Decimal(0))
            drafts.append(DepositMaturityDraft(deposit, account, final))
    return sorted(drafts, key=lambda d: (d.due, isinstance(d, DepositMaturityDraft), d.account.name, d.deposit.name))


def tax_rate_of(account: Account) -> Decimal:
    """The Belka the bank withholds on the Account's interest, as its Tax Regime says."""
    return tax_regime_for(account.account_type).withheld_tax_rate


class Accruals:
    """The interest accrued on each Account's deposits day by day, as History and the Dashboard count it in the
    Account's value: the periods and what paid them are worked out once."""

    def __init__(
        self,
        deposits: Iterable[TermDeposit],
        tax_rates: Mapping[int, Decimal],
        transactions: Iterable[TransactionDraft],
    ) -> None:
        """``tax_rates`` are the Belka withheld on each Account's interest, by Account id (``tax_rates_of``)."""
        self._deposits = [(d, tax_rates[d.account_id], interest_periods(d, tax_rates[d.account_id])) for d in deposits]
        self._paid = paid_periods([d for d, _, _ in self._deposits], transactions)

    def on(self, day: date) -> dict[int, AccruedInterest]:
        """The interest accrued by the end of ``day`` by Account id; an Account with none accrued is left out."""
        accrued: dict[int, AccruedInterest] = {}
        for deposit, tax_rate, periods in self._deposits:
            earned = _accrued(deposit, periods, tax_rate, day, self._paid)
            if earned.gross:
                accrued[deposit.account_id] = accrued.get(deposit.account_id, AccruedInterest()) + earned
        return accrued


def tax_rates_of(accounts: Iterable[Account]) -> dict[int, Decimal]:
    """The Belka withheld on each Account's interest, by Account id."""
    return {account.id: tax_rate_of(account) for account in accounts}


def locked_capital(deposits: Iterable[TermDeposit], day: date) -> dict[int, Decimal]:
    """The cash each Account holds in deposits running at the end of ``day`` (from their start to the day before
    they end), by Account id: their principal. Their interest reaches the cash only once confirmed, so it is left
    out."""
    locked: dict[int, Decimal] = {}
    for deposit in deposits:
        if deposit.start_date <= day < (deposit.closed_on or deposit.maturity):
            locked[deposit.account_id] = locked.get(deposit.account_id, Decimal(0)) + deposit.principal
    return locked


@dataclass(frozen=True)
class DepositRow:
    """A running ``deposit`` on ``account`` as its list shows it on a day: the interest ``accrued`` and not paid,
    what breaking it that day pays back (``break_value``: the principal and the net interest of the periods ended),
    and the ``days_left`` to its maturity."""

    deposit: TermDeposit
    account: Account
    accrued: AccruedInterest
    break_value: Decimal
    days_left: int


def deposit_rows(
    deposits: Iterable[TermDeposit],
    accounts: Sequence[Account],
    transactions: Iterable[TransactionDraft],
    day: date,
    account_id: int | None,
) -> list[DepositRow]:
    """The deposits not closed in the View Scope (``account_id``, ``None`` for Total), the nearest maturity first;
    entered interest pays the periods of every deposit, as the Account's value has it."""
    by_id = {account.id: account for account in accounts}
    deposits = list(deposits)
    running = [d for d in deposits if d.closed_on is None and account_id in (None, d.account_id)]
    paid = paid_periods(deposits, transactions)
    rows = []
    for deposit in running:
        account = by_id[deposit.account_id]
        periods = interest_periods(deposit, tax_rate_of(account))
        ended = sum((p.net for p in periods if p.end <= day), Decimal(0))
        rows.append(
            DepositRow(
                deposit,
                account,
                _accrued(deposit, periods, tax_rate_of(account), day, paid),
                deposit.principal + ended,
                max((deposit.maturity - day).days, 0),
            )
        )
    return sorted(rows, key=lambda row: (row.deposit.maturity, row.account.name, row.deposit.name))
