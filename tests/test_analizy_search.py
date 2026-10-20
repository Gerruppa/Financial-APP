"""The fund and PPK search through analizy.pl (issue #60, spec #56), on saved, trimmed responses without the network."""

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pytest

from financial_app.domain.instrument_search import FoundListing, InstrumentSearchError
from financial_app.domain.instruments import InstrumentType
from financial_app.domain.prices import ANALIZY
from financial_app.sources.analizy import AnalizySearch

FIXTURES = Path(__file__).parent / "fixtures" / "analizy"
# Without exactly these fields the API answers with HTML or {"error":"Wystapil blad"}
FIELDS = "nazwa,nazwa.ngram,nazwaParasola,nazwaGrupy,firmaZarz,nazwaDawniej,searchBenchmark"


def _saved(url: str) -> str | None:
    """The saved search or quotation response for ``url``; a search without one finds nothing, a quotation is HTTP
    404."""
    parsed = urlparse(url)
    if parsed.path == "/api/search/products":
        params = parse_qs(parsed.query)
        assert params["fields"] == [FIELDS]
        path = FIXTURES / "search" / f"{params['keywords'][0].replace(' ', '_')}.json"
        return path.read_text(encoding="utf-8") if path.is_file() else '{"total": 0, "products": []}'
    path = FIXTURES / f"{parsed.path.removeprefix('/api/quotation/fio/')}.json"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def test_a_name_finds_open_funds_without_insurance_funds_and_their_markup() -> None:
    results = AnalizySearch(_saved).search("PZU Akcji Krakowiak")

    # UPZU31 and UALL121 are UFK; the former name ("d. ...") is left out
    assert results == [
        FoundListing(
            name="PZU Akcji KRAKOWIAK",
            symbol="PZU01",
            market="",
            currency="PLN",
            source_symbols={ANALIZY: "PZU01"},
            fund=True,
            instrument_type=InstrumentType.FUND,
        ),
        # Its quotation is not saved, as when the request fails
        FoundListing(
            name="PZU Akcji KRAKOWIAK E",
            symbol="PZE01",
            market="",
            currency="",
            source_symbols={ANALIZY: "PZE01"},
            fund=True,
            instrument_type=InstrumentType.FUND,
        ),
    ]


def test_closed_end_funds_are_left_out() -> None:
    results = AnalizySearch(_saved).search("Quercus")

    assert [r.symbol for r in results] == ["QRS06", "QRS19", "QRS20", "QRS32"]
    assert results[1].name == "QUERCUS Absolutny"


def test_a_ppk_fund_belongs_to_multi_asset() -> None:
    [result] = AnalizySearch(_saved).search("PPK 2060 PZU")

    assert result == FoundListing(
        name="PPK inPZU 2060",
        symbol="PZU60",
        market="",
        currency="PLN",
        source_symbols={ANALIZY: "PZU60"},
        asset_class="Multi-asset",
        fund=True,
        instrument_type=InstrumentType.FUND,
    )


def test_an_isin_finds_a_foreign_fund_and_carries_it() -> None:
    [result] = AnalizySearch(_saved).search("lu0109392836")

    assert result == FoundListing(
        name="Franklin Technology Fund A (Acc) (USD",
        symbol="FTI022_A_USD",
        market="",
        currency="USD",
        source_symbols={ANALIZY: "FTI022_A_USD"},
        isin="LU0109392836",
        fund=True,
        instrument_type=InstrumentType.FUND,
    )


def test_nothing_found_is_an_empty_list() -> None:
    assert AnalizySearch(_saved).search("FTI068") == []
    assert AnalizySearch(_saved).search("  ") == []


def test_no_network_is_a_polish_error() -> None:
    def offline(url: str) -> str | None:
        raise URLError("offline")

    with pytest.raises(InstrumentSearchError, match="połączyć z analizy.pl"):
        AnalizySearch(offline).search("Quercus")


def test_an_http_error_is_a_polish_error() -> None:
    def failing(url: str) -> str | None:
        raise HTTPError(url, 500, "Server Error", {}, None)  # type: ignore[arg-type]

    with pytest.raises(InstrumentSearchError, match="HTTP 500"):
        AnalizySearch(failing).search("Quercus")


@pytest.mark.parametrize("body", ['{"error":"Wystapil blad"}', "<html></html>", None])
def test_a_changed_response_is_a_polish_error(body: str | None) -> None:
    with pytest.raises(InstrumentSearchError, match="Nieprawidłowa odpowiedź wyszukiwarki analizy.pl"):
        AnalizySearch(lambda url: body).search("Quercus")


def test_every_result_is_a_fund() -> None:
    assert {r.fund for r in AnalizySearch(_saved).search("Quercus")} == {True}


def test_a_products_own_isin_is_taken_when_given() -> None:
    # The search has given none so far, so this response is made up in its layout
    product = {"kod": "FTI022_A_USD", "nazwa": "Franklin Technology", "kodRodzaju": "FZG", "isin": "LU0109392836"}
    body = json.dumps({"products": [product]})

    def fetch(url: str) -> str | None:
        return body if "/search/" in url else None

    [result] = AnalizySearch(fetch).search("Franklin Technology")

    assert result.isin == "LU0109392836"
