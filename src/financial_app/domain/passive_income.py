"""The passive-income calendar (issue #93, spec 10): the Dividends and interest received and the bond coupons forecast,
by month, against the Monthly Income Goal.

Received income is each Dividend's and DRIP's Actual Amount, net of the tax withheld: a Dividend of an Instrument or a
DRIP is a dividend, interest naming a Lot a bond coupon, interest paying a Term Deposit's period deposit interest
(issue #160), other interest (a broker's on free cash) interest. The forecast is the coupons of the Bond Series held
that are not entered yet (``domain.bond_drafts.coupon_drafts``, as the bond calendar shows them), net of the tax the
Account's Tax Regime withholds, and the Term Deposits' periods not paid yet (``domain.term_deposits.deposit_drafts``).
A bond paying its interest only at maturity (EDO, TOS, ...) brings it with its redemption, a Sell, so it is no passive
income here.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from financial_app.domain.bond_drafts import CouponDraft
from financial_app.domain.bonds import add_months
from financial_app.domain.formatting import parse_number
from financial_app.domain.term_deposits import InterestDraft
from financial_app.domain.transactions import TransactionDraft

MONTHS = 12


class IncomeKind(StrEnum):
    """Where passive income comes from, in the order shown."""

    DIVIDENDS = "dividends"
    BOND_INTEREST = "bond_interest"
    DEPOSIT_INTEREST = "deposit_interest"
    INTEREST = "interest"

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    IncomeKind.DIVIDENDS: "Dywidendy",
    IncomeKind.BOND_INTEREST: "Odsetki z obligacji",
    IncomeKind.DEPOSIT_INTEREST: "Odsetki z lokat",
    IncomeKind.INTEREST: "Odsetki",
}


@dataclass(frozen=True)
class IncomeItem:
    """Income of ``kind`` paid (or, if ``forecast``, due) on ``day`` into the Account, net in PLN."""

    day: date
    kind: IncomeKind
    account_id: int
    amount: Decimal
    instrument_id: int | None = field(default=None, kw_only=True)
    forecast: bool = field(default=False, kw_only=True)


@dataclass(frozen=True)
class MonthIncome:
    """The income of the month starting on ``month``: received and forecast, each by kind (only kinds with any)."""

    month: date
    received: dict[IncomeKind, Decimal]
    forecast: dict[IncomeKind, Decimal]

    @property
    def received_total(self) -> Decimal:
        return sum(self.received.values(), Decimal(0))

    @property
    def forecast_total(self) -> Decimal:
        return sum(self.forecast.values(), Decimal(0))

    @property
    def total(self) -> Decimal:
        return self.received_total + self.forecast_total

    def progress(self, goal: Decimal | None) -> Decimal | None:
        """The month's income as a fraction of ``goal``; ``None`` without a goal."""
        return None if goal is None else self.total / goal


def received_income(transactions: Iterable[TransactionDraft]) -> list[IncomeItem]:
    """The Dividends, DRIPs and interest among ``transactions``, by day."""
    items = []
    for t in transactions:
        if not t.transaction_type.is_dividend:
            continue
        if t.instrument_id is not None:
            kind = IncomeKind.DIVIDENDS
        elif t.lot_id is not None:
            kind = IncomeKind.BOND_INTEREST
        elif t.term_deposit_id is not None:
            kind = IncomeKind.DEPOSIT_INTEREST
        else:
            kind = IncomeKind.INTEREST
        items.append(IncomeItem(t.date, kind, t.account_id, t.actual_amount, instrument_id=t.instrument_id))
    return sorted(items, key=lambda item: item.day)


def forecast_coupons(drafts: Iterable[CouponDraft]) -> list[IncomeItem]:
    """The coupons not entered yet, as forecast bond interest on their day."""
    return [
        IncomeItem(
            draft.due,
            IncomeKind.BOND_INTEREST,
            draft.account.id,
            draft.net,
            instrument_id=draft.instrument.id,
            forecast=True,
        )
        for draft in drafts
    ]


def forecast_deposit_interest(drafts: Iterable[InterestDraft]) -> list[IncomeItem]:
    """The Term Deposits' periods not paid yet, as forecast deposit interest on their last day."""
    return [
        IncomeItem(draft.due, IncomeKind.DEPOSIT_INTEREST, draft.account.id, draft.period.net, forecast=True)
        for draft in drafts
    ]


def income_by_month(items: Iterable[IncomeItem], year: int, account_id: int | None) -> list[MonthIncome]:
    """The twelve months of ``year`` in the View Scope (``account_id``, ``None`` for Total)."""
    months = {month: MonthIncome(date(year, month, 1), {}, {}) for month in range(1, MONTHS + 1)}
    for item in items:
        if item.day.year != year or account_id not in (None, item.account_id):
            continue
        sums = months[item.day.month].forecast if item.forecast else months[item.day.month].received
        sums[item.kind] = sums.get(item.kind, Decimal(0)) + item.amount
    return [MonthIncome(month.month, _ordered(month.received), _ordered(month.forecast)) for month in months.values()]


def monthly_average(items: Iterable[IncomeItem], today: date, account_id: int | None) -> Decimal:
    """The income received in the View Scope over the twelve whole months before ``today``'s, per month."""
    this_month = today.replace(day=1)
    first = add_months(this_month, -MONTHS)
    received = sum(
        (
            item.amount
            for item in items
            if not item.forecast and account_id in (None, item.account_id) and first <= item.day < this_month
        ),
        Decimal(0),
    )
    return received / MONTHS


def parse_income_goal(text: str) -> Decimal | None:
    """The Monthly Income Goal typed in PLN: ``None`` when left empty; raises ValueError unless a positive amount."""
    if not text.strip():
        return None
    try:
        goal = parse_number(text)
    except ValueError:
        raise ValueError("Cel musi być kwotą w zł.") from None
    if goal <= 0:
        raise ValueError("Cel musi być większy od zera.")
    return goal


def _ordered(sums: dict[IncomeKind, Decimal]) -> dict[IncomeKind, Decimal]:
    return {kind: sums[kind] for kind in IncomeKind if kind in sums}
