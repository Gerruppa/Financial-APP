"""A fund's profile from Yahoo ``quoteSummary`` (issue #188, spec 3.2): the TER, the fund size and the issuer. The API
is undocumented and wants a cookie and a crumb, kept in memory for the session and fetched again once after a 401.
Every failure gives no profile, as the card simply shows nothing then."""

import json
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError
from urllib.parse import quote as url_quote

from financial_app.domain.fund_profile import FundProfile, Holding, largest_holdings

COOKIE_URL = "https://fc.yahoo.com"
CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
SUMMARY_URL = (
    "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
    "?modules=summaryDetail,fundProfile,defaultKeyStatistics,topHoldings&crumb={crumb}"
)
UNAUTHORIZED = 401


@dataclass(frozen=True)
class Reply:
    """An HTTP reply: its status, body and the first ``name=value`` cookie it set ("" when none)."""

    status: int
    body: str = ""
    cookie: str = ""


# (url, Cookie header) -> reply; network failures raise OSError
Transport = Callable[[str, str], Reply]


def fetch_reply(url: str, cookie: str) -> Reply:
    """The reply of ``url``, an HTTP error status included, as the cookie comes with Yahoo's 404."""
    headers = {"User-Agent": "Mozilla/5.0", **({"Cookie": cookie} if cookie else {})}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as response:
            return Reply(
                response.status, response.read().decode("utf-8"), _cookie_of(response.headers.get_all("Set-Cookie"))
            )
    except HTTPError as exc:
        return Reply(exc.code, "", _cookie_of(exc.headers.get_all("Set-Cookie")))


def _cookie_of(set_cookies: list[str] | None) -> str:
    return set_cookies[0].split(";")[0] if set_cookies else ""


class YahooFundProfiles:
    """Fund profiles by Yahoo symbol, each asked once per session; ``transport`` is injectable so tests run on saved
    responses."""

    def __init__(self, transport: Transport = fetch_reply) -> None:
        self.transport = transport
        self._lock = threading.Lock()
        self._credentials: tuple[str, str] | None = None
        self._profiles: dict[str, FundProfile | None] = {}

    def profile(self, symbol: str) -> FundProfile | None:
        """The profile of ``symbol``, or ``None`` when Yahoo gives nothing or fails."""
        symbol = symbol.strip().upper()
        with self._lock:
            if symbol not in self._profiles:
                self._profiles[symbol] = self._ask(symbol)
            return self._profiles[symbol]

    def _ask(self, symbol: str) -> FundProfile | None:
        try:
            reply = self._summary(symbol)
            if reply.status == UNAUTHORIZED:
                self._credentials = None
                reply = self._summary(symbol)
            return _parse(reply.body) if reply.status == 200 else None
        except OSError, ValueError:
            return None

    def _summary(self, symbol: str) -> Reply:
        cookie, crumb = self._credentials or self._login()
        return self.transport(SUMMARY_URL.format(symbol=url_quote(symbol, safe=""), crumb=url_quote(crumb)), cookie)

    def _login(self) -> tuple[str, str]:
        cookie = self.transport(COOKIE_URL, "").cookie
        crumb = self.transport(CRUMB_URL, cookie)
        if not cookie or crumb.status != 200 or not crumb.body:
            raise OSError("Yahoo gave no crumb")
        self._credentials = cookie, crumb.body
        return self._credentials


def _parse(body: str) -> FundProfile | None:
    try:
        result = json.loads(body, parse_float=Decimal)["quoteSummary"]["result"][0]
    except ValueError, KeyError, IndexError, TypeError:
        return None
    if not isinstance(result, dict):
        return None
    detail = result.get("summaryDetail") or {}
    fund = result.get("fundProfile") or {}
    statistics = result.get("defaultKeyStatistics") or {}
    ter = _raw((fund.get("feesExpensesInvestment") or {}).get("annualReportExpenseRatio")) or _raw(
        statistics.get("annualReportExpenseRatio")
    )
    size = _raw(detail.get("totalAssets")) or _raw(statistics.get("totalAssets"))
    currency = str(detail.get("currency") or "")
    profile = FundProfile(
        ter_percent=None if ter is None else (ter * 100).normalize(),
        size=size if size is not None and currency else None,
        size_currency=currency if size is not None else "",
        issuer=str(fund.get("family") or ""),
        holdings=_holdings(result.get("topHoldings")),
    )
    return None if profile.empty else profile


def _holdings(top: object) -> tuple[Holding, ...]:
    """The holdings of Yahoo's ``topHoldings``: each with a name and a positive share."""
    entries = top.get("holdings") if isinstance(top, dict) else None
    shares = []
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict) and (share := _raw(entry.get("holdingPercent"))) is not None:
            shares.append((str(entry.get("holdingName") or entry.get("symbol") or ""), share))
    return largest_holdings(shares)


def _raw(value: object) -> Decimal | None:
    """The ``raw`` number of a Yahoo value, ``None`` when it has none ({}) or it is not a positive number."""
    if not isinstance(value, dict) or "raw" not in value:
        return None
    try:
        number = Decimal(str(value["raw"]))
    except InvalidOperation:
        return None
    return number if number > 0 else None
