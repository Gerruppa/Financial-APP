"""The tile grid's balanced columns: no tile alone on the last row while the window is wide enough."""

import pytest

from financial_app.ui.tile_grid import balanced_columns


@pytest.mark.parametrize(
    ("count", "columns"), [(9, 3), (10, 4), (7, 4), (8, 4), (5, 3), (4, 4), (3, 3), (1, 1), (0, 1)]
)
def test_the_tiles_fill_the_fewest_rows_evenly(count: int, columns: int) -> None:
    style = balanced_columns(count, 4, "14rem")

    assert f"/ {columns}))" in style
    assert style.startswith("grid-template-columns: repeat(auto-fill, minmax(max(14rem, ")
