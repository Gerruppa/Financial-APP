"""Investment Strategies in the window (issue #76): the Strategie inwestycyjne tab, the Dashboard section and the
notice after a price refresh."""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.strategy import ClassTarget, Strategy
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes, list_instruments
from financial_app.persistence.strategies import list_strategies, save_strategy
from financial_app.persistence.transactions import add_transactions
from financial_app.sources.history import QuoteHistory
from financial_app.sources.nbp import NbpRates
from financial_app.sources.portfolio_history import PortfolioHistory
from financial_app.ui.shell import build_shell

NBSP = "\N{NO-BREAK SPACE}"
TODAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 9, 0)
IKE, XTB = 1, 2


def _pln(text: str) -> str:
    return text.replace(" ", NBSP) + f"{NBSP}zł"


def _percent(text: str) -> str:
    return f"{text}{NBSP}%"


def _pp(text: str) -> str:
    return f"{text}{NBSP}pp"


def _class_id(engine: Engine, name: str) -> int:
    return next(c.id for c in list_asset_classes(engine) if c.name == name)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """IKE: 1000 PLN in, 6 PZU (Akcje polskie) at 100, 400 PLN cash left; XTB: 1000 PLN in, 10 CSPX (Akcje
    zagraniczne) at 100. So Akcje polskie 600, Akcje zagraniczne 1000 and Gotówka 400 of 2000 PLN."""
    engine = init_db(tmp_path / "app.sqlite3")
    add_account(engine, AccountDraft("IKE", "mBank", AccountType.IKE, ("PLN",)))
    add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",)))
    pzu = InstrumentDraft("PZU", _class_id(engine, "Akcje polskie"), "PLN", manual_price=Decimal(100))
    cspx = InstrumentDraft("CSPX", _class_id(engine, "Akcje zagraniczne"), "PLN", manual_price=Decimal(100))
    pzu_id, cspx_id = add_instrument(engine, pzu).id, add_instrument(engine, cspx).id
    add_instrument(engine, InstrumentDraft("ACWI", _class_id(engine, "Akcje zagraniczne"), "PLN"))
    add_transactions(
        engine,
        [
            TransactionDraft(IKE, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(1000)),
            TransactionDraft(XTB, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(1000)),
            buy_or_sell(IKE, date(2026, 8, 4), TransactionType.BUY, pzu_id, Decimal(6), Decimal(100)),
            buy_or_sell(XTB, date(2026, 8, 4), TransactionType.BUY, cspx_id, Decimal(10), Decimal(100)),
        ],
    )
    return engine


def _thirty_sixty_ten(engine: Engine, account_id: int | None = None) -> Strategy:
    return Strategy(
        account_id,
        {
            _class_id(engine, "Akcje polskie"): ClassTarget(Decimal(30)),
            _class_id(engine, "Akcje zagraniczne"): ClassTarget(Decimal(60)),
            _class_id(engine, "Gotówka"): ClassTarget(Decimal(10)),
        },
    )


async def _inline(function: Callable[..., list[DayValue]], *args: object) -> list[DayValue]:
    return function(*args)


def _shell(engine: Engine) -> Callable[[], None]:
    quotes = QuoteHistory(engine, lambda url: "Brak danych", lambda: TODAY, lambda: NOW, lambda url: None)
    history = PortfolioHistory(engine, quotes, NbpRates(engine), lambda: TODAY, _inline)
    return lambda: build_shell(engine, sources={}, now=lambda: NOW, history=history)


def _rows(user: User, marker: str) -> list[list[str]]:
    """The rows with ``marker`` top to bottom, each as its texts."""
    rows = sorted(user.find(marker=marker).elements, key=lambda element: element.id)
    return [[d.text for d in row.descendants() if isinstance(d, ui.label) and d.text] for row in rows]


async def test_targets_set_in_the_tab_show_each_class_against_its_target_and_band(engine: Engine) -> None:
    async with user_simulation(_shell(engine)) as user:
        await user.open("/strategie")
        await user.should_see(marker="strategy-row")
        user.find(marker="edit-targets").click()
        await user.should_see(marker="targets-dialog")
        user.find(marker=f"target-{_class_id(engine, 'Akcje polskie')}").type("30")
        user.find(marker=f"target-{_class_id(engine, 'Akcje zagraniczne')}").type("60")
        user.find(marker=f"target-{_class_id(engine, 'Gotówka')}").type("10")
        user.find(marker=f"band-{_class_id(engine, 'Gotówka')}").clear().type("12")
        await user.should_see(f"Razem: {_percent('100,00')}")
        user.find(marker="save-targets").click()

        await user.should_see(marker="band-yellow")
        assert _rows(user, "strategy-row") == [
            [
                "Gotówka",
                _pln("400,00"),
                _percent("20,00"),
                f"{_percent('10,00')} ± {_pp('12')}",
                _pp("+10,00"),
                _pln("-200,00"),
            ],
            [
                "Akcje polskie",
                _pln("600,00"),
                _percent("30,00"),
                f"{_percent('30,00')} ± {_pp('5')}",
                _pp("0,00"),
                _pln("0,00"),
            ],
            [
                "Akcje zagraniczne",
                _pln("1 000,00"),
                _percent("50,00"),
                f"{_percent('60,00')} ± {_pp('5')}",
                _pp("-10,00"),
                _pln("+200,00"),
            ],
        ]
        assert len(user.find(marker="band-green").elements) == 2
    assert list_strategies(engine)[None].class_targets[_class_id(engine, "Gotówka")] == ClassTarget(
        Decimal(10), Decimal(12)
    )


async def test_a_planned_deposit_is_split_without_selling_and_total_names_the_accounts_to_buy_on(
    engine: Engine,
) -> None:
    save_strategy(engine, _thirty_sixty_ten(engine))
    async with user_simulation(_shell(engine)) as user:
        await user.open("/strategie")
        await user.should_see(marker="rebalancing-deposit", content=_pln("2 000,00"))

        user.find(marker="planned-deposit").type("2000")

        await user.should_see(marker=f"deposit-{_class_id(engine, 'Akcje zagraniczne')}", content=_pln("1 400,00"))
        await user.should_see(marker=f"deposit-{_class_id(engine, 'Akcje polskie')}", content=_pln("600,00"))
        await user.should_see(marker=f"accounts-{_class_id(engine, 'Akcje zagraniczne')}", content="Kup na: XTB")
        await user.should_see(marker=f"accounts-{_class_id(engine, 'Akcje polskie')}", content="Kup na: IKE")


def _instrument_id(engine: Engine, name: str) -> int:
    return next(i.id for i in list_instruments(engine) if i.name == name)


async def test_instrument_targets_split_a_class_part_of_the_deposit_and_may_name_one_not_held(engine: Engine) -> None:
    save_strategy(engine, _thirty_sixty_ten(engine))
    stocks = _class_id(engine, "Akcje zagraniczne")
    async with user_simulation(_shell(engine)) as user:
        await user.open("/strategie")
        user.find(marker=f"edit-instrument-targets-{stocks}").click()
        await user.should_see(marker="instrument-targets-dialog")
        user.find(marker=f"instrument-target-{_instrument_id(engine, 'CSPX')}").type("50")
        user.find(marker=f"instrument-target-{_instrument_id(engine, 'ACWI')}").type("40")
        user.find(marker="save-instrument-targets").click()
        await user.should_see(marker="instrument-split-blocked")

        user.find(marker=f"edit-instrument-targets-{stocks}").click()
        user.find(marker=f"instrument-target-{_instrument_id(engine, 'ACWI')}").clear().type("50")
        user.find(marker="save-instrument-targets").click()
        await user.should_not_see(marker="instrument-split-blocked")
        user.find(marker="planned-deposit").type("2000")

        # The class's 1400 PLN first brings ACWI up to CSPX, then both together
        await user.should_see(f"z wpłaty {_pln('1 200,00')}")
        assert _rows(user, "instrument-row")[-2:] == [
            ["CSPX", _pln("1 000,00"), _percent("100,00"), f"cel {_percent('50,00')}", f"z wpłaty {_pln('200,00')}"],
            ["ACWI", _pln("0,00"), _percent("0,00"), f"cel {_percent('50,00')}", f"z wpłaty {_pln('1 200,00')}"],
        ]
    assert list_strategies(engine)[None].instrument_targets == {
        _instrument_id(engine, "CSPX"): Decimal(50),
        _instrument_id(engine, "ACWI"): Decimal(50),
    }


async def _open_scope(user: User, account_id: int) -> None:
    user.find(marker="view-scope").click()
    await user.should_see(marker="scope-menu")
    user.find(marker=f"scope-{account_id}").click()


async def test_an_account_shows_its_structure_until_it_gets_a_strategy_of_its_own(engine: Engine) -> None:
    save_strategy(engine, _thirty_sixty_ten(engine))
    async with user_simulation(_shell(engine)) as user:
        await user.open("/strategie")
        await user.should_see(marker="edit-targets")
        await _open_scope(user, IKE)

        await user.should_see("Konto „IKE” nie ma własnej strategii")
        assert [row[:3] for row in _rows(user, "strategy-row")] == [
            ["Gotówka", _pln("400,00"), _percent("40,00")],
            ["Akcje polskie", _pln("600,00"), _percent("60,00")],
        ]
        user.find(marker="create-strategy").click()
        await user.should_see(marker="delete-strategy")
        assert IKE in list_strategies(engine)

        user.find(marker="delete-strategy").click()
        await user.should_see(marker="create-strategy")
    assert IKE not in list_strategies(engine)


async def test_the_dashboard_section_shows_the_classes_and_the_planned_deposit_split(engine: Engine) -> None:
    save_strategy(engine, _thirty_sixty_ten(engine))
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        # Computing History redraws the Dashboard
        await user.should_see(marker="total-net-deposits", content=_pln("2 000,00"))
        with user.scope(marker="dashboard-strategy"):
            await user.should_see(marker="band-yellow")
            await user.should_see(marker="rebalancing-deposit", content=_pln("2 000,00"))
            user.find(marker="planned-deposit").type("200")
            await user.should_see(marker=f"deposit-{_class_id(engine, 'Akcje zagraniczne')}", content=_pln("200,00"))
            await user.should_not_see(marker="edit-targets")
            user.find(marker="strategy-details").click()
        await user.should_see(marker="edit-targets")


async def test_a_price_refresh_names_the_classes_outside_their_band(engine: Engine) -> None:
    save_strategy(engine, _thirty_sixty_ten(engine))
    async with user_simulation(_shell(engine)) as user:
        await user.open("/")
        user.find(marker="refresh-prices").click()

        await user.should_see(
            f"Poza pasmem tolerancji: Total: Gotówka ({_pp('+10,00')}), Akcje zagraniczne ({_pp('-10,00')})."
        )
