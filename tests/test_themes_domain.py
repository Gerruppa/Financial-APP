"""The window's Theme (issue #174): Jasny or Golden, remembered as text."""

import pytest

from financial_app.domain.themes import Theme, parse_theme


def test_each_theme_has_a_polish_label() -> None:
    assert [theme.label for theme in Theme] == ["Jasny", "Golden"]


@pytest.mark.parametrize("theme", list(Theme))
def test_a_theme_reads_back_from_its_setting(theme: Theme) -> None:
    assert parse_theme(theme.value) is theme


@pytest.mark.parametrize("text", [None, "", "dark", "GOLDEN"])
def test_nothing_or_unknown_text_is_jasny(text: str | None) -> None:
    assert parse_theme(text) is Theme.LIGHT
