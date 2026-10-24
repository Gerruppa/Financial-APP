"""A fund's profile from Yahoo (issue #188): the TER, the fund size and the issuer, each known or not."""

from dataclasses import dataclass
from decimal import Decimal

from financial_app.domain.formatting import NBSP, format_number

BILLION = Decimal(10) ** 9
MILLION = Decimal(10) ** 6


@dataclass(frozen=True)
class FundProfile:
    """What a source tells of a fund; ``ter_percent`` is a percent (0.2 for 0.20%), ``size`` the fund size in
    ``size_currency``, and ``issuer`` its issuer's name; each is empty when the source does not give it. A size
    without a currency is never kept."""

    ter_percent: Decimal | None = None
    size: Decimal | None = None
    size_currency: str = ""
    issuer: str = ""

    @property
    def empty(self) -> bool:
        return self.ter_percent is None and self.size is None and not self.issuer


def format_fund_size(size: Decimal, currency: str) -> str:
    """A fund size in Polish words, e.g. "88,97 mld USD" or "450,00 mln EUR"."""
    if size >= BILLION:
        return f"{format_number(size / BILLION)}{NBSP}mld{NBSP}{currency}"
    if size >= MILLION:
        return f"{format_number(size / MILLION)}{NBSP}mln{NBSP}{currency}"
    return f"{format_number(size, 0)}{NBSP}{currency}"
