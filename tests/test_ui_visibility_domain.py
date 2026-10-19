"""What the window shows (issue #155): the Dashboard elements and tabs that can be hidden, the Podstawowy and Pełny
View Profiles, and the hidden elements remembered as text."""

from financial_app.domain.ui_visibility import (
    ELEMENTS,
    Profile,
    parse_visibility,
    preset_hidden,
    profile_of,
    visibility_setting,
)

BASIC_SHOWN = {
    "tile-value",
    "tile-net-deposits",
    "tile-unrealized",
    "account-table",
    "chart-value",
    "chart-allocation",
    "sayings",
}
ALWAYS_SHOWN_TABS = {"tab-", "tab-portfolio", "tab-transakcje", "tab-ustawienia"}


def test_every_element_has_a_unique_key_and_a_polish_label() -> None:
    keys = [element.key for element in ELEMENTS]
    assert len(keys) == len(set(keys))
    assert all(element.label for element in ELEMENTS)
    assert {"tile-xirr", "chart-drawdown", "strategy", "tab-obligacje"} <= set(keys)


def test_the_always_shown_tabs_cannot_be_hidden() -> None:
    assert not ALWAYS_SHOWN_TABS & {element.key for element in ELEMENTS}


def test_full_hides_nothing() -> None:
    assert preset_hidden(Profile.FULL) == frozenset()
    assert profile_of(frozenset()) is Profile.FULL


def test_basic_shows_three_tiles_the_account_table_and_two_charts_and_no_optional_tab() -> None:
    hidden = preset_hidden(Profile.BASIC)

    shown = {element.key for element in ELEMENTS} - hidden
    assert shown == BASIC_SHOWN
    assert profile_of(hidden) is Profile.BASIC


def test_podstawowy_saved_before_the_sayings_is_still_podstawowy_and_shows_them() -> None:
    saved = frozenset(preset_hidden(Profile.BASIC) - {"sayings"})

    assert profile_of(saved) is Profile.BASIC
    assert "sayings" not in preset_hidden(Profile.BASIC)


def test_any_other_choice_is_custom() -> None:
    assert profile_of(frozenset({"chart-xirr"})) is Profile.CUSTOM
    assert profile_of(preset_hidden(Profile.BASIC) - {"tab-obligacje"}) is Profile.CUSTOM


def test_the_hidden_elements_round_trip_as_text() -> None:
    hidden = frozenset({"chart-xirr", "tab-benchmarki", "tile-cash"})

    text = visibility_setting(hidden)

    assert text == '["chart-xirr", "tab-benchmarki", "tile-cash"]'
    assert parse_visibility(text) == hidden


def test_unknown_keys_or_unreadable_text_show_everything_else() -> None:
    assert parse_visibility('["chart-xirr", "chart-gone"]') == {"chart-xirr"}
    assert parse_visibility("not json") == frozenset()
    assert parse_visibility('{"a": 1}') == frozenset()
    assert parse_visibility(None) == frozenset()
