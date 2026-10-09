"""Currency codes (spec 3.2: base PLN, any NBP table-A currency)."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

_CURRENCY_CODE = re.compile(r"[A-Z]{3}")


def is_currency_code(code: str) -> bool:
    """Whether ``code`` looks like an upper-case three-letter ISO code, e.g. PLN."""
    return _CURRENCY_CODE.fullmatch(code) is not None


@dataclass(frozen=True)
class NbpRate:
    """An NBP table A mid rate: how many PLN one unit of ``currency`` cost, as published in ``table``."""

    currency: str
    rate: Decimal
    published_on: date
    table: str


class MissingNbpRateError(ValueError):
    """No NBP Rate could be found, so the Tax Amount cannot be computed; the message is shown in the UI (Polish).

    Saving is blocked rather than silently using 0 zł (spec 3.3, 9.3).
    """
