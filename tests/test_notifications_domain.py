"""Tests of the notification list: its keys, which are unread and the remembered read keys."""

from datetime import date

from financial_app.domain.notifications import (
    Notification,
    drafts_notification,
    dump_read,
    maturing_notification,
    parse_read,
    unread,
)


def test_drafts_key_changes_with_count_and_latest_due() -> None:
    first = drafts_notification("drafts", "Do zatwierdzenia", "/obligacje", 2, date(2026, 10, 1))
    more = drafts_notification("drafts", "Do zatwierdzenia", "/obligacje", 3, date(2026, 10, 1))
    later = drafts_notification("drafts", "Do zatwierdzenia", "/obligacje", 2, date(2026, 10, 5))
    assert first is not None and more is not None and later is not None
    assert len({first.key, more.key, later.key}) == 3
    assert first.text == "Do zatwierdzenia: 2"


def test_no_drafts_gives_no_notification() -> None:
    assert drafts_notification("drafts", "Do zatwierdzenia", "/obligacje", 0, None) is None


def test_maturing_names_the_day_and_the_series() -> None:
    notification = maturing_notification("EDO0136", date(2026, 11, 3))
    assert notification.text == "Zapada 03.11.2026: EDO0136"
    assert notification.path == "/obligacje"


def test_unread_drops_the_read_keys() -> None:
    a, b = Notification("a", "A", "/"), Notification("b", "B", "/")
    assert unread([a, b], frozenset({"a"})) == [b]


def test_read_keys_round_trip_and_bad_text_is_empty() -> None:
    assert parse_read(dump_read({"b", "a"})) == frozenset({"a", "b"})
    assert parse_read(None) == frozenset()
    assert parse_read("not json") == frozenset()
