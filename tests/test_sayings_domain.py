"""The saying of the day (issue #178): one line a day in the menu."""

from datetime import date, timedelta

from financial_app.domain.sayings import SAYINGS, saying_of_the_day

DAY = date(2026, 10, 19)


def test_every_saying_comes_up_once_in_as_many_days_as_there_are_sayings() -> None:
    days = [DAY + timedelta(days=n) for n in range(len(SAYINGS))]

    assert {saying_of_the_day(day) for day in days} == set(SAYINGS)


def test_every_saying_names_its_work() -> None:
    assert all(saying.text and saying.work for saying in SAYINGS)
