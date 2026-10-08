"""Polish number formatting shared by every screen (spec section 5).

Thousands are grouped with non-breaking spaces and a non-breaking space separates
the number from its unit, so an amount never wraps across lines.
"""

from decimal import ROUND_HALF_UP, Decimal

NBSP = " "


def format_number(value: float | Decimal, decimals: int = 2, signed: bool = False) -> str:
    """Format a number the Polish way: decimal comma, non-breaking thousands separators."""
    # str() first so a float like 2.675 rounds as written, not as its binary approximation
    rounded = Decimal(str(value)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    if rounded.is_zero():
        rounded = abs(rounded)  # never show "-0,00"
    sign = "+" if signed else ""
    return f"{rounded:{sign},.{decimals}f}".replace(",", NBSP).replace(".", ",")


def format_pln(value: float | Decimal, signed: bool = False) -> str:
    """Format an amount in PLN, e.g. 15912.3 -> '15 912,30 zł' (non-breaking spaces)."""
    return f"{format_number(value, signed=signed)}{NBSP}zł"


def format_percent(value: float | Decimal, decimals: int = 2, signed: bool = False) -> str:
    """Format a value already expressed in percent, e.g. 6.4 -> '6,40 %'."""
    return f"{format_number(value, decimals, signed)}{NBSP}%"
