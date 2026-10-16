"""The bond data sources of Stage 3 (spec 3.4.1): the MF file, GUS CPI and the NBP reference rate, parsed from saved
files and kept in SQLite, fetched at most once a day."""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError

import pytest
from sqlalchemy import Engine

from financial_app.domain.bonds import BondDataError, BondType, CpiReading, ReferenceRate, SeriesTerms
from financial_app.persistence.bond_data import (
    bond_data_statuses,
    load_cpi,
    load_reference_rates,
    load_series_terms,
    save_series_terms,
)
from financial_app.persistence.db import init_db
from financial_app.sources.bond_data import (
    GUS,
    GUS_HOST,
    GUS_PAGE,
    MF,
    MF_HOST,
    MF_PAGE,
    NBP_RATES,
    NBP_REFERENCE,
    BondDataSources,
    GusCpi,
    MfBondFile,
    NbpReferenceRates,
    bond_data_due,
    parse_gus_csv,
    parse_mf_file,
    parse_nbp_rates,
    refresh_bond_data,
)

FIXTURES = Path(__file__).parent / "fixtures"
MF_FILE = (FIXTURES / "mf" / "dane_obligacji_detalicznych.xls").read_bytes()
GUS_CSV = (FIXTURES / "gus" / "cpi.csv").read_bytes()
NBP_XML = (FIXTURES / "nbp_reference" / "stopy_procentowe_archiwum.xml").read_bytes()
MF_FILE_URL = MF_HOST + "/attachment/3d42a295-18af-43c6-b56d-de975030f64a"
GUS_CSV_URL = (
    GUS_HOST + "/download/gfx/portalinformacyjny/pl/defaultstronaopisowa/4741/1/1/"
    "miesiecznewskaznikicentowarowiuslugkonsumpcyjnychod1982roku_8.csv"
)
SITE = {
    MF_PAGE: (FIXTURES / "mf" / "page.html").read_bytes(),
    MF_FILE_URL: MF_FILE,
    GUS_PAGE: (FIXTURES / "gus" / "page.html").read_bytes(),
    GUS_CSV_URL: GUS_CSV,
    NBP_RATES: NBP_XML,
}
MONDAY = datetime(2026, 10, 12, 9, 0)


def _site(url: str) -> bytes:
    return SITE[url]


def _offline(url: str) -> bytes:
    raise OSError("no network")


@pytest.fixture(scope="module")
def series() -> dict[str, SeriesTerms]:
    return {terms.series: terms for terms in parse_mf_file(MF_FILE)}


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def test_the_mf_file_gives_every_series_of_each_type(series: dict[str, SeriesTerms]) -> None:
    counts = {bond_type: sum(t.bond_type is bond_type for t in series.values()) for bond_type in BondType}

    assert counts == {
        BondType.OTS: 109,
        BondType.ROR: 53,
        BondType.DOR: 53,
        BondType.TOS: 51,
        BondType.COI: 325,
        BondType.EDO: 265,
        BondType.ROS: 121,
        BondType.ROD: 121,
    }


def test_a_new_edo_series_has_its_first_year_rate_and_margin_only(series: dict[str, SeriesTerms]) -> None:
    assert series["EDO0536"] == SeriesTerms(
        series="EDO0536",
        isin="PL0000119145",
        sale_start=date(2026, 5, 1),
        sale_end=date(2026, 5, 31),
        issue_price=Decimal(100),
        rollover_price=Decimal("99.9"),
        margin=Decimal("0.02"),
        rates=(Decimal("0.0535"),) + (None,) * 9,
        interest=(None,),
    )


def test_a_matured_edo_series_has_the_rate_of_every_year_without_the_float_noise(
    series: dict[str, SeriesTerms],
) -> None:
    edo = series["EDO0525"]

    assert edo.rates[1] == Decimal("0.015")
    assert edo.rates[8] == Decimal("0.176")
    assert edo.interest == (Decimal("73.77"),)


def test_a_one_row_header_gives_one_rate_and_no_margin(series: dict[str, SeriesTerms]) -> None:
    ots = series["OTS0127"]

    assert (ots.rates, ots.interest, ots.margin, ots.rollover_price) == (
        (Decimal("0.02"),),
        (Decimal("0.5"),),
        None,
        Decimal(100),
    )
    assert series["TOS0825"].rates == (Decimal("0.065"),)


def test_ror_and_dor_have_a_rate_and_a_coupon_per_month(series: dict[str, SeriesTerms]) -> None:
    ror, dor = series["ROR0926"], series["DOR0624"]

    assert len(ror.rates) == len(ror.interest) == 12
    assert (ror.rates[0], ror.interest[0], ror.margin) == (Decimal("0.05"), Decimal("0.42"), Decimal(0))
    assert len(dor.rates) == len(dor.interest) == 24
    assert dor.margin == Decimal("0.0025")


def test_coi_has_a_rate_and_a_coupon_per_year(series: dict[str, SeriesTerms]) -> None:
    coi = series["COI0929"]

    assert coi.rates == (Decimal("0.0575"), Decimal("0.045"), None, None)
    assert coi.interest == (Decimal("5.75"), Decimal("4.5"), None, None)


def test_family_bonds_cannot_be_bought_in_a_rollover(series: dict[str, SeriesTerms]) -> None:
    assert series["ROS0932"].rollover_price is None
    assert series["ROD1038"].rollover_price is None


def test_a_broken_mf_file_says_so() -> None:
    with pytest.raises(BondDataError, match="Plik MF z danymi obligacji jest nieczytelny"):
        parse_mf_file(b"<html>not a spreadsheet</html>")


def test_the_mf_file_is_found_through_its_page() -> None:
    assert len(MfBondFile(_site).series()) == 1098


def test_an_mf_page_without_the_file_says_the_page_may_have_changed() -> None:
    with pytest.raises(BondDataError, match="strona mogła się zmienić"):
        MfBondFile(lambda url: b"<html></html>").series()


def test_no_network_asks_to_check_the_connection() -> None:
    with pytest.raises(BondDataError, match="Nie udało się pobrać strony MF z obligacjami. Sprawdź połączenie"):
        MfBondFile(_offline).series()


def test_an_http_error_names_its_code() -> None:
    def forbidden(url: str) -> bytes:
        raise HTTPError(url, 403, "Forbidden", None, None)  # type: ignore[arg-type]

    with pytest.raises(BondDataError, match="Serwer zwrócił błąd 403 przy pobieraniu stóp procentowych NBP"):
        NbpReferenceRates(forbidden).rates()


def test_gus_gives_both_indices_of_each_published_month() -> None:
    readings = parse_gus_csv(GUS_CSV)

    assert readings[0] == CpiReading(2025, 1, Decimal("104.9"), Decimal("101.0"))
    assert readings[-1] == CpiReading(2026, 8, Decimal("103.4"), Decimal("100.3"))
    assert len(readings) == 20  # September to December 2026 are not out yet


def test_the_gus_csv_is_found_through_its_page() -> None:
    assert GusCpi(_site).readings() == parse_gus_csv(GUS_CSV)


def test_a_gus_csv_in_another_layout_says_so() -> None:
    with pytest.raises(BondDataError, match="nieznany układ kolumn"):
        parse_gus_csv("Rok;Miesiąc\n2026;1\n".encode("cp1250"))


def test_the_nbp_archive_gives_the_reference_rate_as_a_fraction() -> None:
    rates = parse_nbp_rates(NBP_XML)

    assert rates[0] == ReferenceRate(date(1998, 2, 26), Decimal("0.24"))
    assert rates[-1] == ReferenceRate(date(2026, 3, 5), Decimal("0.0375"))


def test_a_broken_nbp_archive_says_so() -> None:
    with pytest.raises(BondDataError, match="Nieprawidłowy plik stóp procentowych NBP"):
        parse_nbp_rates(b"<stopy_procentowe_archiwum><pozycje")


def _sources(fetch: Callable[[str], bytes]) -> BondDataSources:
    return BondDataSources(MfBondFile(fetch).series, GusCpi(fetch).readings, NbpReferenceRates(fetch).rates)


def test_a_refresh_saves_the_three_sources(engine: Engine) -> None:
    assert refresh_bond_data(engine, _sources(_site), lambda: MONDAY) == {}

    assert load_series_terms(engine) == {terms.series: terms for terms in parse_mf_file(MF_FILE)}
    assert load_cpi(engine) == parse_gus_csv(GUS_CSV)
    assert load_reference_rates(engine) == parse_nbp_rates(NBP_XML)
    assert {key: status.succeeded_at for key, status in bond_data_statuses(engine).items()} == {
        MF: MONDAY,
        GUS: MONDAY,
        NBP_REFERENCE: MONDAY,
    }


def test_a_saved_series_keeps_its_periods_even_when_none_is_published(engine: Engine) -> None:
    terms = SeriesTerms(
        "EDO1036", "PL0", date(2026, 10, 1), date(2026, 10, 31), Decimal(100), None, None, (None,), (None,)
    )

    save_series_terms(engine, [terms])

    assert load_series_terms(engine) == {"EDO1036": terms}


def test_a_second_refresh_the_same_day_fetches_nothing(engine: Engine) -> None:
    refresh_bond_data(engine, _sources(_site), lambda: MONDAY)
    asked: list[str] = []

    def counting(url: str) -> bytes:
        asked.append(url)
        return SITE[url]

    refresh_bond_data(engine, _sources(counting), lambda: datetime(2026, 10, 12, 18, 0))

    assert asked == []
    assert not bond_data_due(bond_data_statuses(engine), datetime(2026, 10, 12, 18, 0))
    assert bond_data_due(bond_data_statuses(engine), datetime(2026, 10, 13, 9, 0))


def test_a_failing_source_keeps_its_copy_and_never_stops_the_others(engine: Engine) -> None:
    refresh_bond_data(engine, _sources(_site), lambda: MONDAY)
    tuesday = datetime(2026, 10, 13, 9, 0)

    def mf_down(url: str) -> bytes:
        if url.startswith(MF_HOST):
            raise OSError("no network")
        return SITE[url]

    failures = refresh_bond_data(engine, _sources(mf_down), lambda: tuesday)

    assert list(failures) == [MF]
    assert "EDO0536" in load_series_terms(engine)
    statuses = bond_data_statuses(engine)
    assert (statuses[MF].succeeded_at, statuses[MF].failed_at) == (MONDAY, tuesday)
    assert "Sprawdź połączenie" in (statuses[MF].error or "")
    assert (statuses[GUS].succeeded_at, statuses[GUS].error) == (tuesday, None)
    # Failing, MF is tried again the same day
    assert bond_data_due(statuses, datetime(2026, 10, 13, 18, 0))


def test_a_later_success_clears_the_failure(engine: Engine) -> None:
    refresh_bond_data(engine, _sources(_offline), lambda: MONDAY)

    refresh_bond_data(engine, _sources(_site), lambda: datetime(2026, 10, 12, 10, 0))

    assert all(status.error is None for status in bond_data_statuses(engine).values())


def test_an_unexpected_error_counts_as_that_source_failing(engine: Engine) -> None:
    def broken() -> list[SeriesTerms]:
        raise RuntimeError("boom")

    sources = BondDataSources(broken, GusCpi(_site).readings, NbpReferenceRates(_site).rates)

    assert refresh_bond_data(engine, sources, lambda: MONDAY) == {MF: "Nieoczekiwany błąd źródła: boom"}
