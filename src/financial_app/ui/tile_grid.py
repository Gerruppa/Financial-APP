"""The columns of a grid of tiles (the Dashboard's totals, the Sell Summary's figures), balanced so that no tile is left
alone on the last row: nine tiles stand 3 by 3 rather than 4, 4 and 1."""

from math import ceil

# The tiles' gap, Tailwind's gap-4
GAP = "1rem"


def balanced_columns(count: int, max_columns: int, min_width: str) -> str:
    """The grid's ``grid-template-columns`` style: at most as many columns as fill the rows evenly (``count`` tiles in
    the fewest rows of up to ``max_columns``), and fewer, down to one, when a tile would get narrower than
    ``min_width``."""
    rows = max(ceil(count / max_columns), 1)
    columns = max(ceil(count / rows), 1)
    widest = f"calc((100% - {columns - 1} * {GAP}) / {columns})"
    return f"grid-template-columns: repeat(auto-fill, minmax(max({min_width}, {widest}), 1fr))"
