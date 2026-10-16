"""The Wyniki tab's figures: the period's results and the fixed periods per Total and Account (issue #74, spec 6.1)."""

from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.bonds import CpiReading
from financial_app.domain.metrics import MaxDrawdown, xirr
from financial_app.domain.periods import PeriodPreset
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.results import TABLE_PRESETS, period_results, results_rows

IKE, XTB, OLD = 1, 2, 3
ACCOUNTS = [
    Account("IKE", "mBank", AccountType.IKE, ("PLN",), id=IKE),
    Account("XTB", "XTB", AccountType.REGULAR, ("PLN",), id=XTB),
    Account("Stare", "mBank", AccountType.REGULAR, ("PLN",), id=OLD),
]


def _on(day: date, ike: str, xtb: str = "0") -> DayValue:
    """IKE and XTB, 1000 PLN deposited into each before ``day``'s first entry, at the end of ``day``."""
    accounts = {IKE: Decimal(ike), XTB: Decimal(xtb)}
    return DayValue(day, accounts, {}, Decimal(2000), {IKE: Decimal(1000), XTB: Decimal(1000)}, frozenset())


def test_the_period_results_hold_the_returns_the_deepest_fall_its_recovery_and_the_volatility() -> None:
    # Mon 5.01 to Fri 9.01: IKE 1000, 1100, 990 (−10 % from the peak), 1100 (won back on 8.01), 1210
    history = [
        _on(date(2026, 1, 5), "1000", "1000"),
        _on(date(2026, 1, 6), "1100", "1000"),
        _on(date(2026, 1, 7), "990", "1000"),
        _on(date(2026, 1, 8), "1100", "1000"),
        _on(date(2026, 1, 9), "1210", "1000"),
    ]

    results = period_results(history, date(2026, 1, 5), date(2026, 1, 9), IKE)

    assert results.twr == Decimal("0.21")
    assert results.xirr == xirr(history, date(2026, 1, 5), date(2026, 1, 9), IKE)
    assert results.max_drawdown == MaxDrawdown(Decimal("-0.1"), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8))
    assert results.recovery_days == 1
    assert results.volatility is not None and results.volatility > 0


def test_a_fall_not_won_back_has_no_recovery_days_and_a_rise_no_drawdown() -> None:
    history = [_on(date(2026, 1, 5), "1000"), _on(date(2026, 1, 6), "900")]

    assert period_results(history, date(2026, 1, 5), date(2026, 1, 6), IKE).recovery_days is None
    rising = period_results(history[:1], date(2026, 1, 5), date(2026, 1, 5), IKE)
    assert rising.max_drawdown is None and rising.recovery_days is None


def test_the_real_return_is_the_twr_after_the_periods_inflation() -> None:
    # +21 % over 5.01–9.01; January's prices rose 3.1 %, so these 4 of its 31 days by 1.031^(4/31)
    history = [_on(date(2026, 1, 5), "1000"), _on(date(2026, 1, 9), "1210")]
    cpi = [CpiReading(2026, 1, None, Decimal("103.1"))]

    results = period_results(history, date(2026, 1, 5), date(2026, 1, 9), IKE, cpi)

    assert results.inflation is not None and results.inflation.complete
    assert results.real_return == Decimal("1.21") / Decimal("1.031") ** (Decimal(4) / 31) - 1
    assert period_results(history, date(2026, 1, 5), date(2026, 1, 9), IKE).real_return is None


def test_an_account_is_charged_inflation_only_from_the_day_it_first_held_something() -> None:
    # XTB is empty until 7.01, so its real return counts January's inflation from then (2 of 31 days)
    history = [
        DayValue(date(2026, 1, 5), {IKE: Decimal(1000)}, {}, Decimal(1000), {IKE: Decimal(1000)}, frozenset()),
        DayValue(
            date(2026, 1, 7),
            {IKE: Decimal(1000), XTB: Decimal(1000)},
            {},
            Decimal(2000),
            {IKE: Decimal(1000), XTB: Decimal(1000)},
            frozenset(),
        ),
        DayValue(
            date(2026, 1, 9),
            {IKE: Decimal(1000), XTB: Decimal(1000)},
            {},
            Decimal(2000),
            {IKE: Decimal(1000), XTB: Decimal(1000)},
            frozenset(),
        ),
    ]
    cpi = [CpiReading(2026, 1, None, Decimal("103.1"))]

    xtb = period_results(history, date(2026, 1, 5), date(2026, 1, 9), XTB, cpi)
    total = period_results(history, date(2026, 1, 5), date(2026, 1, 9), None, cpi)

    assert xtb.inflation is not None and xtb.inflation.rate == Decimal("1.031") ** (Decimal(2) / 31) - 1
    assert total.inflation is not None and total.inflation.rate == Decimal("1.031") ** (Decimal(4) / 31) - 1


def test_the_total_scope_lists_the_total_then_each_account_holding_something_by_value() -> None:
    history = [_on(date(2026, 1, 5), "1000", "1000"), _on(date(2026, 1, 6), "1100", "1200")]

    rows = results_rows(history, ACCOUNTS, None, date(2026, 1, 6))

    assert [row.account.name if row.account else "Total" for row in rows] == ["Total", "XTB", "IKE"]
    assert rows[0].returns[PeriodPreset.SINCE_INCEPTION].twr == Decimal("0.15")
    assert rows[2].returns[PeriodPreset.SINCE_INCEPTION].twr == Decimal("0.1")


def test_an_account_scope_lists_only_its_account_over_the_ytd_1y_3y_and_since_inception_periods() -> None:
    # 2025-12-31 is the "from" day of YTD, 2025-01-06 that of 1R
    history = [
        _on(date(2025, 1, 6), "1000"),
        _on(date(2025, 12, 31), "1200"),
        _on(date(2026, 1, 6), "1320"),
    ]

    [row] = results_rows(history, ACCOUNTS, IKE, date(2026, 1, 6))

    assert row.account == ACCOUNTS[0]
    assert tuple(row.returns) == TABLE_PRESETS
    assert row.returns[PeriodPreset.YEAR_TO_DATE].twr == Decimal("0.1")
    assert row.returns[PeriodPreset.ONE_YEAR].twr == Decimal("0.32")
    # 3L reaches before the History, so it is clipped to it like Od początku
    assert row.returns[PeriodPreset.THREE_YEARS] == row.returns[PeriodPreset.SINCE_INCEPTION]


def test_an_inactive_account_leaves_the_table_once_emptied() -> None:
    accounts = [*ACCOUNTS[:2], Account("Stare", "mBank", AccountType.REGULAR, ("PLN",), active=False, id=OLD)]

    def on(day: date, old: str) -> DayValue:
        values = {IKE: Decimal(1000), OLD: Decimal(old)}
        return DayValue(day, values, {}, Decimal(1000), {IKE: Decimal(1000), OLD: Decimal(0)}, frozenset())

    emptied = [on(date(2026, 1, 5), "500"), on(date(2026, 1, 6), "0")]
    holding = [on(date(2026, 1, 5), "500"), on(date(2026, 1, 6), "500")]

    assert [row.account for row in results_rows(emptied, accounts, None, date(2026, 1, 6))] == [None, accounts[0]]
    assert [row.account for row in results_rows(holding, accounts, None, date(2026, 1, 6))] == [
        None,
        accounts[0],
        accounts[2],
    ]


def test_no_history_gives_no_rows() -> None:
    assert results_rows([], ACCOUNTS, None, date(2026, 1, 6)) == []
