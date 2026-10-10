"""Which days of a history are still to be fetched, given the days already cached (issue #33)."""

from datetime import date

from financial_app.domain.history import Cover, days_to_fetch, settled

COVER = Cover(date(2026, 3, 1), date(2026, 3, 31))


def test_with_nothing_cached_the_whole_range_is_fetched() -> None:
    assert days_to_fetch(None, date(2026, 3, 1), date(2026, 3, 31)) == [Cover(date(2026, 3, 1), date(2026, 3, 31))]


def test_a_range_inside_the_cached_days_needs_nothing() -> None:
    assert days_to_fetch(COVER, date(2026, 3, 5), date(2026, 3, 20)) == []


def test_only_the_days_before_and_after_the_cached_ones_are_fetched() -> None:
    assert days_to_fetch(COVER, date(2026, 2, 1), date(2026, 4, 15)) == [
        Cover(date(2026, 2, 1), date(2026, 2, 28)),
        Cover(date(2026, 4, 1), date(2026, 4, 15)),
    ]


def test_a_later_range_also_fills_the_gap_so_the_cached_days_stay_one_range() -> None:
    assert days_to_fetch(COVER, date(2026, 5, 1), date(2026, 5, 31)) == [Cover(date(2026, 4, 1), date(2026, 5, 31))]


def test_an_earlier_range_also_fills_the_gap() -> None:
    assert days_to_fetch(COVER, date(2026, 1, 1), date(2026, 1, 31)) == [Cover(date(2026, 1, 1), date(2026, 2, 28))]


def test_an_empty_range_needs_nothing() -> None:
    assert days_to_fetch(None, date(2026, 3, 2), date(2026, 3, 1)) == []


def test_the_cover_grows_by_what_was_fetched() -> None:
    assert Cover(date(2026, 2, 1), date(2026, 2, 28)).joined(COVER) == Cover(date(2026, 2, 1), date(2026, 3, 31))
    assert COVER.joined(None) == COVER


MONDAY = date(2026, 1, 12)


def test_days_well_before_today_are_settled_even_without_quotes() -> None:
    fetched = Cover(date(2026, 1, 1), date(2026, 1, 8))

    assert settled(fetched, None, MONDAY) == fetched


def test_the_last_days_are_settled_only_up_to_the_newest_quote() -> None:
    fetched = Cover(date(2026, 1, 2), date(2026, 1, 11))

    assert settled(fetched, date(2026, 1, 9), MONDAY) == Cover(date(2026, 1, 2), date(2026, 1, 9))
    assert settled(fetched, date(2026, 1, 11), MONDAY) == fetched
    assert settled(fetched, None, MONDAY) == Cover(date(2026, 1, 2), date(2026, 1, 8))
    assert settled(Cover(date(2026, 1, 10), date(2026, 1, 11)), None, MONDAY) is None


def test_ranges_are_split_into_pieces_of_at_most_a_given_length() -> None:
    pieces = Cover(date(2026, 1, 1), date(2026, 3, 10)).split(days=30)

    assert pieces == [
        Cover(date(2026, 1, 1), date(2026, 1, 30)),
        Cover(date(2026, 1, 31), date(2026, 3, 1)),
        Cover(date(2026, 3, 2), date(2026, 3, 10)),
    ]
