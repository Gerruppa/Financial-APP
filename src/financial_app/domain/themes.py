"""The window's Theme (issue #174): Jasny, or Golden with a dark background and gold accents.

Like Wygląd i widoczność it changes only how the window looks; it is remembered as its value, and nothing remembered
(or text naming no Theme) is Jasny.
"""

from enum import Enum


class Theme(Enum):
    LIGHT = "jasny"
    GOLDEN = "golden"

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {Theme.LIGHT: "Jasny", Theme.GOLDEN: "Golden"}


def parse_theme(text: str | None) -> Theme:
    """The remembered Theme; nothing or unknown text is Jasny."""
    return next((theme for theme in Theme if theme.value == text), Theme.LIGHT)
