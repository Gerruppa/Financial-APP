"""The annual PDF report (issue #242): the pages, the Polish letters and the long tables, read back from the file."""

import io
from datetime import date
from decimal import Decimal

from pypdf import PdfReader

from financial_app.domain.report import NOTHING_TO_REPORT, Percent, Report, Section
from financial_app.sources.pdf_report import DISCLAIMER, annual_report_to_pdf

GENERATED = date(2026, 10, 12)


def _pages(data: bytes) -> list[str]:
    return [page.extract_text() for page in PdfReader(io.BytesIO(data)).pages]


def _text(data: bytes) -> str:
    return "\n".join(_pages(data))


def _reports(rows: int = 3) -> list[Report]:
    return [
        Report(
            "wyniki",
            "Wyniki 2025",
            (Section("Wyniki roku", ("Miara", "Wartość"), (("TWR", Percent(Decimal("0.1234"))),)),),
        ),
        Report(
            "podsumowanie-sprzedazy",
            "Sprzedaże 2025",
            (
                Section(
                    "Sprzedaże",
                    ("Instrument", "Zakup", "Liczba", "Wynik"),
                    tuple(("Żółć gęślą jaźń", date(2025, 1, 5), Decimal(10), Decimal("1234.5")) for _ in range(rows)),
                    ("Uwaga: ąęłńóśźż",),
                ),
            ),
        ),
    ]


def test_the_title_page_names_the_scope_the_year_and_the_date() -> None:
    data = annual_report_to_pdf("Wszystkie rachunki", 2025, GENERATED, _reports())

    first = _pages(data)[0]
    assert "Raport roczny 2025" in first
    assert "Wszystkie rachunki" in first
    assert "12.10.2026" in first


def test_the_sections_amounts_dates_and_polish_letters_appear_in_the_text() -> None:
    text = _text(annual_report_to_pdf("mBank IKE", 2025, GENERATED, _reports()))

    text = text.replace(" ", " ")
    for expected in ("Wyniki roku", "Sprzedaże", "Żółć gęślą jaźń", "05.01.2025", "12,34 %", "1 234,50", "ąęłńóśźż"):
        assert expected in text


def test_the_disclaimer_is_on_every_page() -> None:
    pages = _pages(annual_report_to_pdf("Total", 2025, GENERATED, _reports(rows=120)))

    assert all(DISCLAIMER in page for page in pages)


def test_a_long_table_continues_on_the_next_page_with_its_header_repeated() -> None:
    pages = _pages(annual_report_to_pdf("Total", 2025, GENERATED, _reports(rows=120)))

    assert len(pages) >= 4  # the title page, the results and two or more of the sales
    with_header = [page for page in pages if "Instrument" in page and "Zakup" in page]
    assert len(with_header) >= 2


def test_an_empty_report_still_gives_a_valid_pdf_with_its_note() -> None:
    reports = [Report("wyniki", "Wyniki 2025", notes=(NOTHING_TO_REPORT,))]

    data = annual_report_to_pdf("Total", 2025, GENERATED, reports)

    assert len(PdfReader(io.BytesIO(data)).pages) == 2
    assert NOTHING_TO_REPORT in _text(data)
