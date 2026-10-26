"""The header bell's notifications (issue #176) gathered from the database, and the read keys kept in
``app_settings``."""

from datetime import timedelta

from sqlalchemy import Engine

from financial_app.domain.bond_calendar import EventKind, bond_calendar
from financial_app.domain.contribution_limits import limit_bars, over_limit_warning
from financial_app.domain.notifications import (
    Notification,
    drafts_notification,
    dump_read,
    maturing_notification,
    parse_read,
)
from financial_app.persistence.bond_drafts import pending_drafts
from financial_app.persistence.contribution_limits import load_limits
from financial_app.persistence.deposit_drafts import pending_deposit_drafts
from financial_app.persistence.recurring_rules import pending_recurring_drafts
from financial_app.persistence.settings import UI_NOTIFICATIONS_READ, load_setting, save_setting
from financial_app.sources.current_prices import LatestRates
from financial_app.sources.prices import last_refresh
from financial_app.sources.todays_view import todays_view

# How far ahead a maturity is announced
MATURITY_DAYS = 30
SETTINGS_PATH = "/ustawienia"


def collect_notifications(engine: Engine, rates: LatestRates) -> list[Notification]:
    """Every reminder due today: bond and Term Deposit Drafts, Recurring Rule Drafts, Instruments the last refresh
    found no price for, bonds and Term Deposits maturing within ``MATURITY_DAYS`` and Contribution Limits exceeded."""
    view = todays_view(engine, rates)
    today = view.today
    found: list[Notification | None] = []
    bond_drafts = [*pending_drafts(engine, today), *pending_deposit_drafts(engine, today)]
    found.append(
        drafts_notification(
            "drafts",
            "Do zatwierdzenia w Dochodzie stałym",
            "/obligacje",
            len(bond_drafts),
            max((draft.due for draft in bond_drafts), default=None),
        )
    )
    recurring = pending_recurring_drafts(engine, today)
    found.append(
        drafts_notification(
            "recurring",
            "Transakcje cykliczne do zatwierdzenia",
            "/transakcje",
            len(recurring),
            max((draft.due for draft in recurring), default=None),
        )
    )
    status = last_refresh(engine)
    if status is not None and status.failures:
        names = ", ".join(failure.instrument for failure in status.failures)
        found.append(
            Notification(
                f"prices:{status.refreshed_at.isoformat()}", f"Bez wyceny po odświeżeniu: {names}", SETTINGS_PATH
            )
        )
    horizon = today + timedelta(days=MATURITY_DAYS)
    events = bond_calendar(view.positions, view.instruments, view.accounts, view.bonds, today, None)
    found.extend(
        maturing_notification(event.instrument.name, event.day)
        for event in events
        if event.kind is EventKind.MATURITY and event.day <= horizon
    )
    found.extend(
        maturing_notification(deposit.name, deposit.maturity)
        for deposit in view.deposits
        if deposit.closed_on is None and today < deposit.maturity <= horizon
    )
    bars = limit_bars(view.transactions, view.accounts, load_limits(engine), today.year, None)
    found.extend(
        Notification(f"limit:{bar.account_type.value}:{bar.year}:{bar.over}", over_limit_warning(bar), "/")
        for bar in bars
        if bar.over
    )
    return [notification for notification in found if notification is not None]


def load_read(engine: Engine) -> frozenset[str]:
    return parse_read(load_setting(engine, UI_NOTIFICATIONS_READ))


def save_read(engine: Engine, keys: frozenset[str]) -> None:
    save_setting(engine, UI_NOTIFICATIONS_READ, dump_read(keys))
