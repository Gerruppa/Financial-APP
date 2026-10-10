from datetime import date, datetime
from decimal import Decimal

import pytest

from financial_app.domain.formatting import (
    format_amount,
    format_count,
    format_date,
    format_datetime,
    format_exact,
    format_percent,
    format_pln,
    format_quantity,
    format_rate,
    format_unit_price,
    parse_date,
    parse_number,
    parse_ratio,
)

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


@pytest.mark.parametrize(
    ("value", "expected"),
    [(Decimal("0.5"), "0,50"), (Decimal("135.4275"), "135,4275"), (Decimal(12850), "12\xa0850,00")],
)
def test_format_exact_keeps_every_decimal_so_editing_never_rounds(value: Decimal, expected: str) -> None:
    assert format_exact(value) == expected


def test_unit_price_keeps_all_its_decimals() -> None:
    assert format_unit_price(Decimal("45.123")) == f"45,123{NBSP}zł"
    assert format_unit_price(Decimal("45.5")) == f"45,50{NBSP}zł"


def test_unit_price_in_another_currency_shows_its_code() -> None:
    assert format_unit_price(Decimal("150.5"), "USD") == f"150,50{NBSP}USD"


def test_quantity_shows_only_the_decimals_it_has() -> None:
    assert format_quantity(Decimal("10")) == "10"
    assert format_quantity(Decimal("0.50")) == "0,5"
    assert format_quantity(Decimal("1234.5")) == f"1{NBSP}234,5"


def test_amount_in_a_foreign_currency_carries_its_code() -> None:
    assert format_amount(Decimal("-1505"), "USD", signed=True) == f"-1{NBSP}505,00{NBSP}USD"
    assert format_amount(Decimal("12.5"), "PLN") == f"12,50{NBSP}zł"


def test_rate_has_four_decimals_in_pln() -> None:
    assert format_rate(Decimal("3.65")) == f"3,6500{NBSP}zł"


def test_parse_ratio_reads_whole_numbers_around_a_colon() -> None:
    assert parse_ratio("2:1") == (2, 1)
    assert parse_ratio(" 1 : 5 ") == (1, 5)


@pytest.mark.parametrize("text", ["", "2", "2-1", "2:", "1,5:1", "-2:1", "2:1:1"])
def test_parse_ratio_rejects_other_formats(text: str) -> None:
    with pytest.raises(ValueError):
        parse_ratio(text)


def test_a_time_is_shown_day_first_to_the_minute() -> None:
    assert format_datetime(datetime(2026, 10, 9, 8, 5, 59)) == "09.10.2026 08:05"


@pytest.mark.parametrize(
    ("count", "expected"),
    [(1, "1 błąd"), (2, "2 błędy"), (4, "4 błędy"), (5, "5 błędów"), (12, "12 błędów"), (22, "22 błędy")],
)
def test_a_count_takes_the_polish_plural(count: int, expected: str) -> None:
    assert format_count(count, "błąd", "błędy", "błędów") == expected
