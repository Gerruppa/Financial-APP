"""Text stays readable on coloured backgrounds in both Themes: the Investment Strategy's band rows and the Accounts
treemap's tiles reach the WCAG AA contrast of 4.5:1 for normal text."""

from decimal import Decimal

import pytest

from financial_app.domain.strategy import BandStatus
from financial_app.domain.themes import Theme
from financial_app.ui.account_ranking import tile_colours
from financial_app.ui.theme import BAND_COLOURS, TEXT_COLOURS, THEME_COLOURS

AA = 4.5


def _luminance(colour: str) -> float:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(one: str, other: str) -> float:
    light, dark = sorted((_luminance(one), _luminance(other)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_the_contrast_of_black_on_white_is_21() -> None:
    assert _contrast("#000000", "#ffffff") == pytest.approx(21)


@pytest.mark.parametrize("theme", list(Theme))
@pytest.mark.parametrize("status", list(BandStatus))
def test_a_strategy_band_row_is_readable(theme: Theme, status: BandStatus) -> None:
    assert _contrast(TEXT_COLOURS[theme], BAND_COLOURS[theme][status]) >= AA


@pytest.mark.parametrize("theme", list(Theme))
@pytest.mark.parametrize("share", [None, "0", "0.05", "0.15", "0.3", "1", "-0.05", "-0.15", "-0.3", "-1"])
def test_a_treemap_tile_label_is_readable(theme: Theme, share: str | None) -> None:
    colours = tile_colours(None if share is None else Decimal(share), theme)

    assert _contrast(colours.label, colours.background) >= AA


def test_a_golden_tile_without_a_result_is_dark() -> None:
    assert _luminance(tile_colours(Decimal(0), Theme.GOLDEN).background) < 0.05


@pytest.mark.parametrize("theme", list(Theme))
@pytest.mark.parametrize("tone", ["text", "muted", "gain", "loss", "warning"])
def test_every_text_tone_is_readable_on_every_background(theme: Theme, tone: str) -> None:
    colours = THEME_COLOURS[theme]
    # The page, a card, a hovered row and the highlighted field (the transaction dialog's Account)
    for background in ("card", "page", "hover", "field"):
        assert _contrast(colours[tone], colours[background]) >= AA, background
