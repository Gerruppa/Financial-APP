"""A fund's profile (issues #188, #204): from Yahoo the TER, the fund size and the issuer, from analizy.pl the TFI, the
group and the benchmark, each known or not."""

from dataclasses import dataclass
from decimal import Decimal

from financial_app.domain.formatting import NBSP, format_number

BILLION = Decimal(10) ** 9
MILLION = Decimal(10) ** 6


@dataclass(frozen=True)
class FundProfile:
    """What a source tells of a fund; ``ter_percent`` is a percent (0.2 for 0.20%), ``size`` the fund size in
    ``size_currency``, and ``issuer`` its issuer's name; each is empty when the source does not give it. A size
    without a currency is never kept. ``tfi``, ``group`` ("Grupa analizy.pl") and ``benchmark`` are what analizy.pl
    tells of a Polish fund or ETF; ``source`` names where the profile is from, as the card marks it ("wg Yahoo")."""

    ter_percent: Decimal | None = None
    size: Decimal | None = None
    size_currency: str = ""
    issuer: str = ""
    tfi: str = ""
    group: str = ""
    benchmark: str = ""
    source: str = "Yahoo"

    @property
    def empty(self) -> bool:
        return (
            self.ter_percent is None
            and self.size is None
            and not (self.issuer or self.tfi or self.group or self.benchmark)
        )


def format_fund_size(size: Decimal, currency: str) -> str:
    """A fund size in Polish words, e.g. "88,97 mld USD" or "450,00 mln EUR"."""
    if size >= BILLION:
        return f"{format_number(size / BILLION)}{NBSP}mld{NBSP}{currency}"
    if size >= MILLION:
        return f"{format_number(size / MILLION)}{NBSP}mln{NBSP}{currency}"
    return f"{format_number(size, 0)}{NBSP}{currency}"
