"""A Polish fund's, PPK's or GPW ETF's TFI, group and benchmark from the analizy.pl search (issue #204), on saved
responses without the network."""

import json
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

from financial_app.domain.fund_profile import FundProfile
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


def test_an_etf_ticker_with_several_etf_hits_gives_nothing(tmp_path: Path) -> None:
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
