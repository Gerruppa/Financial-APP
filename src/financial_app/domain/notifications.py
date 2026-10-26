"""The header bell's notifications (issue #176): what the app reminds the user of, each with a key that changes when
the reminder changes, so a reminder the user has read comes back unread only when it is something new.

A notification is derived from the current state, never stored; only the keys the user has read are remembered."""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from financial_app.domain.formatting import format_date


@dataclass(frozen=True)
class Notification:
    """A reminder: ``key`` identifies it and its state, ``text`` is shown (Polish), ``path`` is the tab it opens."""

    key: str
    text: str
    path: str


def drafts_notification(kind: str, label: str, path: str, count: int, latest: date | None) -> Notification | None:
    """ "<label>: n" for ``count`` Drafts due; new once another Draft is due or a later one comes."""
    if not count or latest is None:
        return None
    return Notification(f"{kind}:{count}:{latest.isoformat()}", f"{label}: {count}", path)


def maturing_notification(name: str, day: date) -> Notification:
    """A Bond Series or Term Deposit maturing soon on ``day``."""
    return Notification(f"maturing:{name}:{day.isoformat()}", f"Zapada {format_date(day)}: {name}", "/obligacje")


def unread(notifications: Iterable[Notification], read: frozenset[str]) -> list[Notification]:
    return [notification for notification in notifications if notification.key not in read]


def dump_read(keys: Iterable[str]) -> str:
    return json.dumps(sorted(keys))


def parse_read(text: str | None) -> frozenset[str]:
    """The remembered read keys; nothing when none were saved or the text is not a list."""
    if text is None:
        return frozenset()
    try:
        keys = json.loads(text)
    except ValueError:
        return frozenset()
    return frozenset(keys) if isinstance(keys, list) else frozenset()
