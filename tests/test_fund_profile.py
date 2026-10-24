"""A fund's profile from Yahoo quoteSummary (issue #188), on saved responses without the network."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote, urlparse

from financial_app.domain.fund_profile import FundProfile, Holding, format_fund_size
from financial_app.domain.instrument_search import FormFields, FoundListing, fill_empty
from financial_app.sources.fund_profile import COOKIE_URL, CRUMB_URL, Reply, YahooFundProfiles

SUMMARIES = Path(__file__).parent / "fixtures" / "yahoo" / "summary"


class Yahoo:
    """A fake Yahoo: a cookie and a crumb, then the saved summary of a symbol; ``rejections`` summaries are first
    refused with a 401, as when the crumb expired."""

    def __init__(self, rejections: int = 0) -> None:
        self.rejections = rejections
        self.urls: list[str] = []

    def __call__(self, url: str, cookie: str) -> Reply:
        self.urls.append(url)
        if url == COOKIE_URL:
            return Reply(404, "", "A3=cookie")
        if cookie != "A3=cookie":
            return Reply(401)
        if url == CRUMB_URL:
            return Reply(200, f"crumb{self.crumbs()}")
        if self.rejections:
            self.rejections -= 1
            return Reply(401)
        symbol = unquote(urlparse(url).path.rsplit("/", 1)[1])
        path = SUMMARIES / f"{symbol}.json"
        return Reply(200, path.read_text(encoding="utf-8")) if path.is_file() else Reply(404)

    def crumbs(self) -> int:
        return self.urls.count(CRUMB_URL)


def test_ishares_etf_has_a_ter_and_an_issuer_but_no_size() -> None:
    profile = YahooFundProfiles(Yahoo()).profile("IWDA.AS")

    assert profile is not None
    assert replace(profile, holdings=()) == FundProfile(
        Decimal("0.2"), None, "", "BlackRock Asset Management Ireland - ETF"
    )


def test_vanguard_etf_has_a_size_in_its_currency_and_an_issuer_but_no_ter() -> None:
    profile = YahooFundProfiles(Yahoo()).profile("VUAA.L")

    assert profile is not None
    assert replace(profile, holdings=()) == FundProfile(
        None, Decimal("88972738560"), "USD", "Vanguard Group (Ireland) Limited"
    )


def test_a_warsaw_listing_has_no_profile() -> None:
    assert YahooFundProfiles(Yahoo()).profile("ETFBW20TR.WA") is None


def test_an_unknown_symbol_has_no_profile() -> None:
    assert YahooFundProfiles(Yahoo()).profile("NOPE") is None


def test_the_cookie_and_crumb_are_fetched_once_and_each_symbol_is_asked_once() -> None:
    yahoo = Yahoo()
    profiles = YahooFundProfiles(yahoo)

    profiles.profile("IWDA.AS")
    profiles.profile("VUAA.L")
    profiles.profile("iwda.as")

    assert (yahoo.urls.count(COOKIE_URL), yahoo.crumbs(), len(yahoo.urls)) == (1, 1, 4)


def test_a_401_fetches_the_cookie_and_crumb_once_more() -> None:
    yahoo = Yahoo(rejections=1)

    profile = YahooFundProfiles(yahoo).profile("IWDA.AS")

    assert profile is not None and profile.ter_percent == Decimal("0.2")
    assert (yahoo.urls.count(COOKIE_URL), yahoo.crumbs()) == (2, 2)


def test_a_second_401_gives_no_profile() -> None:
    assert YahooFundProfiles(Yahoo(rejections=2)).profile("IWDA.AS") is None


def test_a_network_failure_gives_no_profile() -> None:
    def down(url: str, cookie: str) -> Reply:
        raise OSError("offline")

    assert YahooFundProfiles(down).profile("IWDA.AS") is None


def test_a_size_without_a_currency_is_dropped() -> None:
    body = '{"quoteSummary": {"result": [{"summaryDetail": {"totalAssets": {"raw": 5000000}}}]}}'

    assert YahooFundProfiles(lambda url, cookie: Reply(200, body, "A3=x")).profile("X") is None


def test_a_fund_size_is_written_in_billions_or_millions() -> None:
    assert format_fund_size(Decimal("88972738560"), "USD") == "88,97 mld USD"
    assert format_fund_size(Decimal("450000000"), "EUR") == "450,00 mln EUR"


def test_fill_empty_takes_the_ter_only_while_the_form_has_none() -> None:
    found = FoundListing("Fund", "F", "", "USD", ter_percent=Decimal("0.2"))

    assert fill_empty(FormFields(), found).ter_percent == Decimal("0.2")
    assert fill_empty(FormFields(ter_percent=Decimal("0.07")), found).ter_percent == Decimal("0.07")


def test_ishares_etf_has_its_ten_largest_holdings_with_their_shares_in_percent() -> None:
    profile = YahooFundProfiles(Yahoo()).profile("IWDA.AS")

    assert profile is not None
    assert len(profile.holdings) == 10
    assert profile.holdings[0] == Holding("NVIDIA Corp", Decimal("5.78801"))
    assert profile.holdings_date is None


def test_a_profile_with_only_holdings_is_not_empty() -> None:
    assert not FundProfile(holdings=(Holding("X", Decimal(1)),)).empty
