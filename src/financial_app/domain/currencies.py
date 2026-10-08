"""Currency codes (spec 3.2: base PLN, any NBP table-A currency)."""

import re

_CURRENCY_CODE = re.compile(r"[A-Z]{3}")


def is_currency_code(code: str) -> bool:
    """Whether ``code`` looks like an upper-case three-letter ISO code, e.g. PLN."""
    return _CURRENCY_CODE.fullmatch(code) is not None
