"""The Obligacje tab (L-4, spec 3.4.1): a table of the Bond Series held in the View Scope, expanding to their Lots, with
the gross and the net value (after the early-redemption fee and the Account's tax); and the Dashboard's after-tax toggle
taking the net value."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.bonds import CpiReading, ReferenceRate, SeriesTerms
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.bond_data import save_cpi, save_reference_rates, save_series_terms
from financial_app.persistence.bond_series import series_instrument
from financial_app.persistence.db import init_db
from financial_app.persistence.settings import VIEW_SCOPE, save_setting
from financial_app.persistence.transactions import add_transaction
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell

NBSP = "\xa0"
TODAY = date(2026, 10, 8)


def _terms(series: str, first_rate: str) -> SeriesTerms:
    year, month = 2000 + int(series[5:]) - 10, int(series[3:5])
    rates = (Decimal(first_rate),) + (None,) * 9
    sold = (date(year, month, 1), date(year, month, 28))
    return SeriesTerms(series, "PL0000119145", *sold, Decimal(100), Decimal("99.9"), Decimal("0.02"), rates, (None,))


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    engine = init_db(tmp_path / "app.sqlite3")
    save_series_terms(engine, [_terms("EDO0536", "0.0535"), _terms("EDO0535", "0.0565")])
    save_cpi(engine, [CpiReading(2026, 3, Decimal("103.0"), None)])
    return engine


def _bought(
    engine: Engine, account_name: str, account_type: AccountType, series: str, day: date, quantity: int = 10
) -> int:
    account = add_account(engine, AccountDraft(account_name, "PKO BP", account_type, ("PLN",)))
    instrument, _ = series_instrument(engine, series)
    add_transaction(engine, TransactionDraft(account.id, day, TransactionType.DEPOSIT, Decimal(quantity * 100)))
    add_transaction(
        engine, buy_or_sell(account.id, day, TransactionType.BUY, instrument.id, Decimal(quantity), Decimal(100))
    )
    return account.id


def _shell(engine: Engine) -> None:
    build_shell(engine, NbpRates(engine, fetch=lambda url: None, today=lambda: TODAY))


async def test_the_tab_lists_each_series_with_its_gross_and_net_value(engine: Engine) -> None:
    _bought(engine, "Obligacje", AccountType.BONDS, "EDO0535", date(2025, 5, 22))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/obligacje")

        with user.scope(marker="bonds"):
            await user.should_see("EDO0535")
            await user.should_see(f"1{NBSP}000,00{NBSP}zł")  # paid in
            await user.should_see(f"1{NBSP}076,60{NBSP}zł")  # gross
            await user.should_see(marker="bond-net", content=f"1{NBSP}037,70{NBSP}zł")
            await user.should_see(f"5,00{NBSP}% · rok 2")
            await user.should_see("szacowana (CPI)")
            await user.should_see("22.05.2027")  # next anniversary
            await user.should_see("22.05.2035")  # maturity
            await user.should_not_see(marker="bond-lots")
        user.find(marker="bond-row").click()
        with user.scope(marker="bond-lots"):
            await user.should_see("22.05.2025")
            await user.should_see(f"opłata 30,00{NBSP}zł · podatek 8,90{NBSP}zł")


async def test_an_ots_nets_its_nominal_before_maturity_and_shows_no_year(engine: Engine) -> None:
    ots = SeriesTerms(
        "OTS1026",
        "PL0000119145",
        date(2026, 7, 1),
        date(2026, 7, 31),
        *(Decimal(100),) * 2,
        None,
        (Decimal("0.02"),),
        (None,),
    )
    save_series_terms(engine, [ots])
    _bought(engine, "Obligacje", AccountType.BONDS, "OTS1026", date(2026, 7, 10))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/obligacje")

        with user.scope(marker="bonds"):
            # 90 days at 2% out of 365: 0.49 zł a bond, forfeited when redeemed early
            await user.should_see(f"1{NBSP}004,90{NBSP}zł")
            await user.should_see(marker="bond-net", content=f"1{NBSP}000,00{NBSP}zł")
            await user.should_see(f"2,00{NBSP}%")
            await user.should_not_see("· rok")
            await user.should_see("10.10.2026")  # maturity


async def test_an_ike_withholds_no_tax(engine: Engine) -> None:
    _bought(engine, "IKE", AccountType.IKE, "EDO0535", date(2025, 5, 22))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/obligacje")

        await user.should_see(marker="bond-net", content=f"1{NBSP}046,60{NBSP}zł")


async def test_the_tab_follows_the_view_scope(engine: Engine) -> None:
    _bought(engine, "Obligacje", AccountType.BONDS, "EDO0535", date(2025, 5, 22))
    ike = _bought(engine, "IKE", AccountType.IKE, "EDO0536", date(2026, 5, 22))
    save_setting(engine, VIEW_SCOPE, str(ike))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/obligacje")

        with user.scope(marker="bonds"):
            await user.should_see("EDO0536")
            await user.should_not_see("EDO0535")


async def test_without_bonds_the_tab_says_so(engine: Engine) -> None:
    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/obligacje")

        await user.should_see(marker="bonds-empty")


async def _after_tax(user: User) -> None:
    user.find(marker="after-tax").click()


async def test_the_dashboards_after_tax_toggle_takes_the_bonds_fee_and_tax(engine: Engine) -> None:
    _bought(engine, "Obligacje", AccountType.BONDS, "EDO0535", date(2025, 5, 22))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/")
        await _after_tax(user)

        await user.should_see(marker="total-estimated-tax", content=f"38,90{NBSP}zł")


async def test_a_ror_takes_its_later_months_from_the_nbp_reference_rate(engine: Engine) -> None:
    rates = (Decimal("0.04"),) + (None,) * 11
    ror = SeriesTerms(
        "ROR0827", "PL0000119145", date(2026, 8, 1), date(2026, 8, 31), *(Decimal(100),) * 2, Decimal(0), rates, ()
    )
    save_series_terms(engine, [ror])
    save_reference_rates(engine, [ReferenceRate(date(2026, 3, 5), Decimal("0.0375"))])
    _bought(engine, "Obligacje", AccountType.BONDS, "ROR0827", date(2026, 8, 10))

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/obligacje")

        with user.scope(marker="bonds"):
            # Month 2 (10.09-10.10) at 3.75%, 28 of its 30 days gone: 0.29 zł a bond
            await user.should_see(f"1{NBSP}002,90{NBSP}zł")
            await user.should_see(f"3,75{NBSP}% · miesiąc 2")
            await user.should_see("szacowana (NBP)")
        # Month 1's coupon was paid on 10.09
        with user.scope(marker="bond-drafts"):
            await user.should_see("Odsetki ROR0827")


async def test_the_calendar_lists_the_next_twelve_months(engine: Engine) -> None:
    _bought(engine, "Obligacje", AccountType.BONDS, "EDO0535", date(2025, 5, 22))
    _bought(engine, "Drugie konto", AccountType.BONDS, "EDO0536", date(2026, 6, 3), quantity=5)

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/obligacje")

        with user.scope(marker="bond-calendar"):
            rows = user.find(marker="calendar-row").elements
            assert len(rows) == 2
            await user.should_see("03.06.2027")
            await user.should_see("22.05.2027")
            await user.should_see(f"Rocznica · nowe oprocentowanie 5,00{NBSP}% · rok 3")
            await user.should_see("prognoza (ostatnie CPI)")
            await user.should_see("Drugie konto")


async def test_the_calendar_says_when_nothing_falls_due(engine: Engine) -> None:
    _bought(engine, "Obligacje", AccountType.BONDS, "EDO0537", date(2025, 10, 8))  # no MF terms, so not valued

    async with user_simulation(lambda: _shell(engine)) as user:
        await user.open("/obligacje")

        await user.should_see(marker="calendar-empty")
