from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.formatting import format_date, format_percent, format_pln, parse_date, parse_number

NBSP = " "


def test_pln_amount_uses_decimal_comma_and_non_breaking_spaces() -> None:
    assert format_pln(15912.3) == f"15{NBSP}912,30{NBSP}zł"


def test_pln_amount_groups_millions_and_keeps_sign() -> None:
    assert format_pln(-1234567.891) == f"-1{NBSP}234{NBSP}567,89{NBSP}zł"


def test_pln_amount_rounds_half_up_to_grosze() -> None:
    assert format_pln(Decimal("0.005")) == f"0,01{NBSP}zł"
    assert format_pln(2.675) == f"2,68{NBSP}zł"


def test_small_pln_amount_has_no_thousands_separator() -> None:
    assert format_pln(0) == f"0,00{NBSP}zł"


def test_percent_uses_decimal_comma_and_non_breaking_space_before_sign() -> None:
    assert format_percent(6.4) == f"6,40{NBSP}%"


def test_percent_can_show_explicit_sign_and_custom_precision() -> None:
    assert format_percent(1.25, decimals=1, signed=True) == f"+1,3{NBSP}%"
    assert format_percent(-0.04, decimals=1, signed=True) == f"+0,0{NBSP}%"  # no "-0,0"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1000", Decimal("1000")),
        ("1 000,50", Decimal("1000.50")),
        (f"1{NBSP}000,5{NBSP}zł", Decimal("1000.5")),
        ("0.5", Decimal("0.5")),
        (" -12,3 ", Decimal("-12.3")),
    ],
)
def test_parse_number_reads_amounts_typed_the_polish_way(text: str, expected: Decimal) -> None:
    assert parse_number(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "1,2,3", "NaN", "Infinity"])
def test_parse_number_rejects_text_that_is_not_a_number(text: str) -> None:
    with pytest.raises(ValueError):
        parse_number(text)


def test_date_is_shown_day_first_with_dots() -> None:
    assert format_date(date(2026, 3, 7)) == "07.03.2026"


def test_parse_date_reads_day_first_dates() -> None:
    assert parse_date(" 07.03.2026 ") == date(2026, 3, 7)


@pytest.mark.parametrize("text", ["", "2026-03-07", "31.02.2026", "7/3/2026"])
def test_parse_date_rejects_other_formats_and_impossible_dates(text: str) -> None:
    with pytest.raises(ValueError):
        parse_date(text)
