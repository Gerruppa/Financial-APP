"""The calendar of the Obligacje tab (spec 3.4.1, L-9): what the Bond Series held will bring over the next 12 months.

Each Lot shows its coupons (COI, ROR, DOR: the gross for its bonds and the net after the tax the Account's Tax Regime
withholds on the coupon of one bond, as a coupon Draft will), its anniversaries with the new period's rate (the yearly
types, TOS capitalising its fixed rate; the monthly ROR and DOR have their rate on each coupon) and its maturity (the
nominal with the interest, less the tax, as the maturity Draft redeems it). The rates are labelled as in the table. A
Series not valued yet shows only its maturity, without amounts. The calendar runs from tomorrow to the same day next
year: what falls due today is already a Draft. It later feeds the Stage 5 passive-income calendar.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from enum import StrEnum

from financial_app.domain.accounts import Account
from financial_app.domain.bond_drafts import CouponDraft, MaturityDraft, coupon_drafts, maturity_drafts
from financial_app.domain.bond_valuation import SHORT_TYPES, BondData, PeriodRate, RateLabel, period_rate_text
from financial_app.domain.bonds import MONTHLY_TYPES, TERM_MONTHS, BondType, add_months, bond_type_of
from financial_app.domain.instruments import Instrument
from financial_app.domain.lots import Lot, Position

CALENDAR_MONTHS = 12


class EventKind(StrEnum):
    """What happens on a calendar day, in the order shown on one day."""

    COUPON = "coupon"
    ANNIVERSARY = "anniversary"
    MATURITY = "maturity"


_ORDER = tuple(EventKind)


@dataclass(frozen=True)
class CalendarEvent:
    """A ``kind`` of event of a ``lot`` on ``day``: ``period`` and ``rate`` the coupon's or the new period's (none at
    maturity), ``label`` the most uncertain of the rates it rests on, ``gross`` and ``net`` what is paid out for all
    the Lot's bonds (none on an anniversary or without a value)."""

    day: date
    kind: EventKind
    account: Account
    instrument: Instrument
    lot: Lot
    period: int | None = None
    rate: PeriodRate | None = None
    label: RateLabel | None = None
    gross: Decimal | None = None
    net: Decimal | None = None

    @property
    def quantity(self) -> Decimal:
        return self.lot.quantity

    @property
    def bond_type(self) -> BondType | None:
        return bond_type_of(self.instrument.name)

    @property
    def rate_text(self) -> str | None:
        """The rate with its period, "5,35% · rok 2" or "6,00% · miesiąc 3"; ``None`` without a rate."""
        if self.rate is None:
            return None
        return period_rate_text(self.rate.rate, self.period, monthly=self.bond_type in MONTHLY_TYPES)


def bond_calendar(
    positions: Iterable[Position],
    instruments: Mapping[int, Instrument],
    accounts: Sequence[Account],
    bonds: BondData,
    today: date,
    account_id: int | None,
) -> list[CalendarEvent]:
    """The events of the Bond Series among ``positions`` after ``today`` up to the same day ``CALENDAR_MONTHS`` later,
    in the View Scope (``account_id``, ``None`` for Total), by day. Coupons and maturities are the Drafts that will be
    due by then, so their amounts are what confirming them will save."""
    held = list(positions)
    last = add_months(today, CALENDAR_MONTHS)
    coupons = coupon_drafts(held, instruments, accounts, bonds, last, account_id, entered={})
    matured = maturity_drafts(held, instruments, accounts, bonds, last, account_id)
    events = [
        *(_coupon(draft) for draft in coupons if draft.due > today),
        *_anniversaries(held, instruments, accounts, bonds, today, last, account_id),
        *(_maturity(draft, bonds) for draft in matured if draft.due > today),
    ]
    return sorted(events, key=lambda e: (e.day, _ORDER.index(e.kind), e.account.name, e.instrument.name, e.lot.date))


def _coupon(draft: CouponDraft) -> CalendarEvent:
    rate = draft.coupon.rate
    return CalendarEvent(
        draft.due,
        EventKind.COUPON,
        draft.account,
        draft.instrument,
        draft.lot,
        draft.period,
        rate,
        rate.label,
        draft.gross,
        draft.net,
    )


def _maturity(draft: MaturityDraft, bonds: BondData) -> CalendarEvent:
    """The redemption of all the Lot's bonds at maturity; no amounts while the Series has no value."""
    event = CalendarEvent(draft.due, EventKind.MATURITY, draft.account, draft.instrument, draft.lot)
    price = bonds.price(draft.instrument.id, draft.due)
    value = None if price is None else price.value(draft.lot.date)
    if value is None or draft.redemption is None:
        return event
    return replace(event, label=value.label, gross=draft.redemption.gross, net=draft.redemption.net)


def _anniversaries(
    positions: Iterable[Position],
    instruments: Mapping[int, Instrument],
    accounts: Sequence[Account],
    bonds: BondData,
    today: date,
    last: date,
    account_id: int | None,
) -> list[CalendarEvent]:
    """The yearly anniversaries before maturity after ``today`` up to ``last``: a new rate, or a TOS's interest
    capitalised; none for a bond running months or paying monthly, nor without a rate."""
    by_id = {account.id: account for account in accounts}
    events = []
    for position in positions:
        instrument = instruments[position.instrument_id]
        bond_type = bond_type_of(instrument.name)
        # A Bond Series always has a type; the check only narrows it
        if not instrument.is_bond_series or bond_type is None or account_id not in (None, position.account_id):
            continue
        if bond_type in SHORT_TYPES or bond_type in MONTHLY_TYPES:
            continue
        for lot in position.lots:
            for year in range(1, TERM_MONTHS[bond_type] // 12):
                day = add_months(lot.date, 12 * year)
                price = bonds.price(instrument.id, day) if today < day <= last else None
                value = None if price is None else price.value(lot.date)
                if value is not None:
                    account = by_id[position.account_id]
                    events.append(
                        CalendarEvent(
                            day,
                            EventKind.ANNIVERSARY,
                            account,
                            instrument,
                            lot,
                            value.period,
                            value.rate,
                            value.rate.label,
                        )
                    )
    return events
