from decimal import Decimal

from financial_app.domain.formatting import format_percent, format_pln

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
