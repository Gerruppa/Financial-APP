"""Saving Investment Strategies: Total's and each Account's own (issue #76)."""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft, InstrumentError
from financial_app.domain.strategy import ClassTarget, Strategy
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import (
    add_asset_class,
    add_instrument,
    delete_asset_class,
    delete_instrument,
    list_asset_classes,
)
from financial_app.persistence.reset import clear_portfolio
from financial_app.persistence.strategies import delete_strategy, list_strategies, save_strategy


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _class_id(engine: Engine, name: str) -> int:
    return next(c.id for c in list_asset_classes(engine) if c.name == name)


def _ike(engine: Engine) -> int:
    return add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN",))).id


def _cspx(engine: Engine) -> int:
    return add_instrument(engine, InstrumentDraft("CSPX", _class_id(engine, "Akcje zagraniczne"), "PLN")).id


def test_a_new_database_has_no_strategy(engine: Engine) -> None:
    assert list_strategies(engine) == {}


def test_total_and_an_account_keep_their_own_strategies(engine: Engine) -> None:
    ike, cspx = _ike(engine), _cspx(engine)
    stocks, bonds = _class_id(engine, "Akcje zagraniczne"), _class_id(engine, "Obligacje skarbowe polskie")
    total = Strategy(None, {stocks: ClassTarget(Decimal("60.5"), Decimal(3)), bonds: ClassTarget(Decimal("39.5"))})
    own = Strategy(ike, {stocks: ClassTarget(Decimal(100))}, {cspx: Decimal(100)})

    save_strategy(engine, total)
    save_strategy(engine, own)

    assert list_strategies(engine) == {None: total, ike: own}


def test_saving_a_strategy_again_replaces_its_targets(engine: Engine) -> None:
    stocks, bonds = _class_id(engine, "Akcje zagraniczne"), _class_id(engine, "Obligacje skarbowe polskie")
    save_strategy(engine, Strategy(None, {stocks: ClassTarget(Decimal(60)), bonds: ClassTarget(Decimal(40))}))

    save_strategy(engine, Strategy(None, {bonds: ClassTarget(Decimal(100))}))

    assert list_strategies(engine) == {None: Strategy(None, {bonds: ClassTarget(Decimal(100))})}


def test_an_account_strategy_without_targets_still_exists_until_deleted(engine: Engine) -> None:
    ike = _ike(engine)
    save_strategy(engine, Strategy(ike))
    assert list_strategies(engine) == {ike: Strategy(ike)}

    delete_strategy(engine, ike)

    assert list_strategies(engine) == {}


def test_a_class_in_a_strategy_cannot_be_deleted(engine: Engine) -> None:
    crypto = add_asset_class(engine, "Krypto").id
    save_strategy(engine, Strategy(None, {crypto: ClassTarget(Decimal(5))}))

    with pytest.raises(InstrumentError, match="Krypto.*strategii inwestycyjnej"):
        delete_asset_class(engine, crypto)


def test_deleting_an_instrument_drops_its_instrument_targets(engine: Engine) -> None:
    cspx = _cspx(engine)
    save_strategy(engine, Strategy(None, instrument_targets={cspx: Decimal(100)}))

    delete_instrument(engine, cspx)

    assert list_strategies(engine) == {None: Strategy(None)}


def test_clearing_the_portfolio_removes_every_strategy(engine: Engine) -> None:
    ike, cspx = _ike(engine), _cspx(engine)
    stocks = _class_id(engine, "Akcje zagraniczne")
    save_strategy(engine, Strategy(None, {stocks: ClassTarget(Decimal(100))}))
    save_strategy(engine, Strategy(ike, {stocks: ClassTarget(Decimal(100))}, {cspx: Decimal(100)}))

    clear_portfolio(engine)

    assert list_strategies(engine) == {}
