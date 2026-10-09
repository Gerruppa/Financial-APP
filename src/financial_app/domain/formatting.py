"""Polish number and date formatting shared by every screen (spec section 5), and parsing of what the user types.

Thousands are grouped with non-breaking spaces and a non-breaking space separates
the number from its unit, so an amount never wraps across lines.
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

NBSP = " "
DATE_FORMAT = "%d.%m.%Y"


def format_number(value: float | Decimal, decimals: int = 2, signed: bool = False) -> str:
    """Format a number the Polish way: decimal comma, non-breaking thousands separators."""
    # str() first so a float like 2.675 rounds as written, not as its binary approximation
    rounded = Decimal(str(value)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    if rounded.is_zero():
        rounded = abs(rounded)  # never show "-0,00"
    sign = "+" if signed else ""
    return f"{rounded:{sign},.{decimals}f}".replace(",", NBSP).replace(".", ",")


def format_exact(value: Decimal) -> str:
    """Format a stored value for an edit field with all its decimals (at least two), so re-saving never rounds it."""
    exponent = value.as_tuple().exponent
    return format_number(value, decimals=max(2, -exponent if isinstance(exponent, int) else 0))


def format_quantity(value: Decimal) -> str:
    """Format a quantity with only the decimals it has, e.g. 10 -> '10', 0.50 -> '0,5'."""
    exponent = value.normalize().as_tuple().exponent
    return format_number(value, decimals=max(0, -exponent if isinstance(exponent, int) else 0))


def format_pln(value: float | Decimal, signed: bool = False) -> str:
    """Format an amount in PLN, e.g. 15912.3 -> '15 912,30 zł' (non-breaking spaces)."""
    return format_amount(value, "PLN", signed)


def format_amount(value: float | Decimal, currency: str, signed: bool = False) -> str:
    """Format an amount in ``currency``, e.g. '1 505,00 USD', or '12,50 zł' for PLN."""
    return f"{format_number(value, signed=signed)}{NBSP}{currency_unit(currency)}"


def currency_unit(currency: str) -> str:
    """How an amount's currency is written: 'zł' for PLN, otherwise its code."""
    return "zł" if currency == "PLN" else currency


def format_unit_price(value: Decimal, currency: str = "PLN") -> str:
    """Format a unit price with all its decimals (at least two), e.g. 45.123 -> '45,123 zł', or '150,50 USD'."""
    return f"{format_exact(value)}{NBSP}{currency_unit(currency)}"


def format_rate(value: Decimal) -> str:
    """Format an exchange rate in PLN per unit with four decimals, e.g. 3.6045 -> '3,6045 zł'."""
    return f"{format_number(value, decimals=4)}{NBSP}zł"


def format_percent(value: float | Decimal, decimals: int = 2, signed: bool = False) -> str:
    """Format a value already expressed in percent, e.g. 6.4 -> '6,40 %'."""
    return f"{format_number(value, decimals, signed)}{NBSP}%"


def format_date(value: date) -> str:
    """Format a date day-first, e.g. 2026-03-07 -> '07.03.2026'."""
    return value.strftime(DATE_FORMAT)


def parse_number(text: str) -> Decimal:
    """Read a number typed the Polish way ('1 000,50', '0,5 %', '12 zł'); raises ValueError if it is not one."""
    cleaned = text.strip().removesuffix("zł").removesuffix("%")
    cleaned = cleaned.replace(" ", "").replace(NBSP, "").replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"not a number: {text!r}") from None
    if not value.is_finite():
        raise ValueError(f"not a number: {text!r}")
    return value


def parse_date(text: str) -> date:
    """Read a day-first date ('07.03.2026'); raises ValueError for any other format or an impossible date."""
    return datetime.strptime(text.strip(), DATE_FORMAT).date()
