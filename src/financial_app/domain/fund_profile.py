"""A fund's profile (issues #188, #204, #203): from Yahoo the TER, the fund size, the issuer and the largest holdings,
from analizy.pl the TFI, the group, the benchmark and, for a Polish fund, the largest holdings, each known or not."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_app.domain.formatting import NBSP, format_number

BILLION = Decimal(10) ** 9
MILLION = Decimal(10) ** 6


@dataclass(frozen=True)
class Holding:
    """One of a fund's largest holdings: its name and its share of the fund in percent (5.79 for 5.79%)."""

    name: str
    percent: Decimal


@dataclass(frozen=True)
class FundProfile:
    """What a source tells of a fund; ``ter_percent`` is a percent (0.2 for 0.20%), ``size`` the fund size in
    ``size_currency``, and ``issuer`` its issuer's name; each is empty when the source does not give it. A size
    without a currency is never kept. ``tfi``, ``group`` ("Grupa analizy.pl") and ``benchmark`` are what analizy.pl
    tells of a Polish fund or ETF; ``holdings`` are the largest holdings, largest first, as of ``holdings_date`` when
    the source gives the day; ``source`` names where the profile is from, as the card marks it ("wg Yahoo")."""

    ter_percent: Decimal | None = None
    size: Decimal | None = None
    size_currency: str = ""
    issuer: str = ""
    tfi: str = ""
    group: str = ""
    benchmark: str = ""
    holdings: tuple[Holding, ...] = ()
    holdings_date: date | None = None
    source: str = "Yahoo"

    @property
    def empty(self) -> bool:
        return (
            self.ter_percent is None
            and self.size is None
            and not (self.issuer or self.tfi or self.group or self.benchmark or self.holdings)
        )


def format_fund_size(size: Decimal, currency: str) -> str:
    """A fund size in Polish words, e.g. "88,97 mld USD" or "450,00 mln EUR"."""
    if size >= BILLION:
        return f"{format_number(size / BILLION)}{NBSP}mld{NBSP}{currency}"
    if size >= MILLION:
        return f"{format_number(size / MILLION)}{NBSP}mln{NBSP}{currency}"
    return f"{format_number(size, 0)}{NBSP}{currency}"
