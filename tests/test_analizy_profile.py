"""A Polish fund's, PPK's or GPW ETF's TFI, group and benchmark from the analizy.pl search (issue #204), on saved
responses without the network."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

from financial_app.domain.fund_profile import FundProfile, Holding
from financial_app.sources.analizy import AnalizyFundProfiles

SEARCHES = Path(__file__).parent / "fixtures" / "analizy" / "search"


class Search:
    """A fake analizy.pl: the saved search for a keyword, nothing found for an unknown one."""

    def __init__(self) -> None:
        self.keywords: list[str] = []

    def __call__(self, url: str) -> str | None:
        keyword = parse_qs(urlparse(url).query)["keywords"][0]
        self.keywords.append(keyword)
        path = SEARCHES / f"{keyword}.json"
        return path.read_text(encoding="utf-8") if path.is_file() else '{"total": 0, "products": []}'


def test_a_gpw_etf_found_by_its_ticker_gives_its_tfi_group_and_benchmark() -> None:
    profile = AnalizyFundProfiles(Search()).etf_profile("ETFBW20TR")

    assert profile == FundProfile(
        tfi="AgioFunds TFI", group="akcji polskich uniwersalne", benchmark="WIG20TR Indeks", source="analizy.pl"
    )


def test_a_fund_found_by_its_fund_code_has_no_benchmark_when_analizy_says_it_has_none() -> None:
    profile = AnalizyFundProfiles(Search()).fund_profile("qrs20")

    assert profile == FundProfile(tfi="QUERCUS TFI", group="rynku surowców - metale szlachetne", source="analizy.pl")


def test_a_ppk_fund_has_its_group_and_no_benchmark() -> None:
    profile = AnalizyFundProfiles(Search()).fund_profile("PZU60")

    assert profile == FundProfile(tfi="TFI PZU", group="zdefiniowanej daty PPK 2060", source="analizy.pl")


def test_nothing_is_given_for_a_code_the_search_does_not_return() -> None:
    profiles = AnalizyFundProfiles(Search())

    assert profiles.fund_profile("NOPE") is None
    assert profiles.etf_profile("NOPE") is None
    # Quercus.json holds several funds, none with this code
    assert profiles.fund_profile("QRS99") is None


def test_an_etf_ticker_with_several_etf_hits_gives_nothing() -> None:
    def two(url: str) -> str:
        product = {"kod": "E_1", "kodRodzaju": "ETF", "firmaZarz": "X TFI", "nazwaGrupy": "g"}
        return json.dumps({"products": [product, {**product, "kod": "E_2"}]})

    assert AnalizyFundProfiles(two).etf_profile("ETF") is None


def test_only_an_etf_hit_counts_for_a_ticker() -> None:
    def fund(url: str) -> str:
        return json.dumps({"products": [{"kod": "PZU60", "kodRodzaju": "PPK", "firmaZarz": "TFI PZU"}]})

    assert AnalizyFundProfiles(fund).etf_profile("PZU60") is None


def test_a_failure_or_a_bad_answer_gives_nothing() -> None:
    def down(url: str) -> str:
        raise URLError("offline")

    assert AnalizyFundProfiles(down).fund_profile("PZU60") is None
    assert AnalizyFundProfiles(lambda url: "<html>").fund_profile("PZU60") is None
    assert AnalizyFundProfiles(lambda url: None).etf_profile("ETFBW20TR") is None


def test_each_query_is_asked_once_per_session() -> None:
    search = Search()
    profiles = AnalizyFundProfiles(search)

    profiles.fund_profile("PZU60")
    profiles.fund_profile("pzu60")
    profiles.etf_profile("ETFBW20TR")

    assert search.keywords == ["PZU60", "ETFBW20TR"]


def test_a_failed_search_is_asked_again_next_time() -> None:
    answers = [None, (SEARCHES / "PZU60.json").read_text(encoding="utf-8")]

    def flaky(url: str) -> str | None:
        if "top10" in url:
            return None
        answer = answers.pop(0)
        if answer is None:
            raise URLError("offline")
        return answer

    profiles = AnalizyFundProfiles(flaky)

    assert profiles.fund_profile("PZU60") is None
    assert profiles.fund_profile("PZU60") is not None


TOP10 = Path(__file__).parent / "fixtures" / "analizy" / "top10"


class Funds(Search):
    """A fake analizy.pl that also gives the saved ten largest holdings of a Fund Code (404 when it has none)."""

    def __call__(self, url: str) -> str | None:
        if "/api/assets/top10/" in url:
            self.keywords.append(url)
            path = TOP10 / f"{url.rsplit('/', 1)[1]}.json"
            return path.read_text(encoding="utf-8") if path.is_file() else None
        return super().__call__(url)


def test_a_ppk_fund_has_its_ten_largest_holdings_and_the_day_of_their_state() -> None:
    profile = AnalizyFundProfiles(Funds()).fund_profile("PZU60")

    assert profile is not None
    assert profile.tfi == "TFI PZU"
    assert len(profile.holdings) == 10
    assert profile.holdings[0] == Holding("iShares Core S&P 500 ETF (USD)", Decimal("10.93572191914804"))
    assert profile.holdings_date == date(2026, 6, 30)


def test_a_fund_without_top_holdings_keeps_its_profile() -> None:
    profile = AnalizyFundProfiles(Funds()).fund_profile("qrs20")

    assert profile is not None
    assert profile.tfi == "QUERCUS TFI"
    assert profile.holdings == ()


def test_a_failed_or_unsuccessful_top10_does_not_spoil_the_profile() -> None:
    def broken(url: str) -> str | None:
        if "top10" in url:
            return '{"success": false}'
        return Search()(url)

    profile = AnalizyFundProfiles(broken).fund_profile("PZU60")

    assert profile is not None
    assert profile.holdings == ()


def test_an_etf_is_not_asked_for_top_holdings() -> None:
    search = Funds()

    AnalizyFundProfiles(search).etf_profile("ETFBW20TR")

    assert not any("top10" in asked for asked in search.keywords)
