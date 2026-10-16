"""The window's change events (issue #112): each change reaches every element that declared it, once per publish."""

from functools import partial

import pytest

from financial_app.ui.changes import Change, ChangeEvents


@pytest.mark.parametrize("change", list(Change))
def test_each_change_reaches_its_subscribers(change: Change) -> None:
    events = ChangeEvents()
    heard: list[str] = []
    events.subscribe(lambda: heard.append("wanted"), {change})
    events.subscribe(lambda: heard.append("other"), set(Change) - {change})

    events.publish(change)

    assert heard == ["wanted"]


def test_a_subscriber_of_several_published_changes_redraws_once() -> None:
    events = ChangeEvents()
    heard: list[str] = []
    events.subscribe(lambda: heard.append("page"), {Change.PRICES, Change.BOND_DATA})

    events.publish(Change.PRICES, Change.BOND_DATA)

    assert heard == ["page"]


def test_a_change_published_by_a_subscriber_joins_the_running_publish() -> None:
    # History outdated by new prices, as the shell subscribes it: first, so the History pages redraw after it, once
    events = ChangeEvents()
    heard: list[str] = []

    def outdate_history() -> None:
        heard.append("invalidated")
        events.publish(Change.HISTORY)

    events.subscribe(outdate_history, {Change.PRICES})
    events.subscribe(lambda: heard.append("dashboard"), {Change.HISTORY})
    events.subscribe(lambda: heard.append("results"), {Change.BOND_DATA, Change.HISTORY})

    events.publish(Change.PRICES)

    assert heard == ["invalidated", "dashboard", "results"]


def test_a_change_published_for_an_earlier_subscriber_still_reaches_it() -> None:
    events = ChangeEvents()
    heard: list[str] = []
    events.subscribe(lambda: heard.append("dashboard"), {Change.HISTORY})
    events.subscribe(lambda: events.publish(Change.HISTORY), {Change.PRICES})

    events.publish(Change.PRICES)

    assert heard == ["dashboard"]


def test_subscribers_redraw_in_their_subscription_order() -> None:
    events = ChangeEvents()
    heard: list[int] = []
    for index in range(3):
        events.subscribe(partial(heard.append, index), {Change.SCOPE})

    events.publish(Change.SCOPE)

    assert heard == [0, 1, 2]


def test_a_later_publish_reaches_the_subscribers_again() -> None:
    events = ChangeEvents()
    heard: list[str] = []
    events.subscribe(lambda: heard.append("page"), {Change.TRANSACTIONS})

    events.publish(Change.TRANSACTIONS)
    events.publish(Change.TRANSACTIONS)

    assert heard == ["page", "page"]
