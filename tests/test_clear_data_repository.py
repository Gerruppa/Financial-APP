"""Clearing the portfolio: everything the user entered goes, the Asset Classes return to their defaults."""

import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import DEFAULT_ASSET_CLASSES, InstrumentDraft
from financial_app.domain.prices import BOSSA, YAHOO, Quote, default_fallback_order
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell
from financial_app.persistence import reset
from financial_app.persistence.accounts import add_account, list_accounts
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import (
    add_asset_class,
    add_instrument,
    list_asset_classes,
    list_instruments,
    rename_asset_class,
    set_fallback_order,
)
from financial_app.persistence.models import (
    AssetClassRow,
    Base,
    BenchmarkRow,
    ClassTargetRow,
    InstrumentTargetRow,
    InvestmentGoalRow,
    MultiAssetShareRow,
    OnClear,
    PriceFailureRow,
    QuoteHistoryRow,
    RateCorrectionRow,
    RecurringRuleRow,
    RecurringRuleSkipRow,
    SkippedBrokerRow,
    StrategyRow,
    ValuationSnapshotRow,
)
from financial_app.persistence.nbp_rates import cache_rate, cached_rate
from financial_app.persistence.quotes import latest_quotes, save_quote
from financial_app.persistence.reset import BackupError, PortfolioCounts, clear_portfolio, portfolio_counts
from financial_app.persistence.transactions import add_transaction, list_transactions


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return tmp_path / "app.sqlite3"


@pytest.fixture
def engine(db_file: Path) -> Engine:
    return init_db(db_file)


def _fill(engine: Engine) -> None:
    account = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN", "USD")))
    classes = list_asset_classes(engine)
    rename_asset_class(engine, classes[1].id, "Akcje PL")
    extra = add_asset_class(engine, "Moja klasa")
    instrument = add_instrument(engine, InstrumentDraft("GPW:PKN", extra.id, "PLN"))
    add_transaction(
        engine,
        TransactionDraft(account.id, date(2024, 1, 2), TransactionType.DEPOSIT, Decimal(1000)),
    )
    add_transaction(
        engine,
        buy_or_sell(account.id, date(2024, 1, 3), TransactionType.BUY, instrument.id, Decimal(2), Decimal(100)),
    )


def test_counts_show_what_the_portfolio_holds(engine: Engine) -> None:
    _fill(engine)

    assert portfolio_counts(engine) == PortfolioCounts(accounts=1, instruments=1, transactions=2)


def test_clearing_removes_accounts_instruments_and_transactions(engine: Engine) -> None:
    _fill(engine)

    clear_portfolio(engine)

    assert list_accounts(engine) == []
    assert list_instruments(engine) == []
    assert list_transactions(engine) == []
    assert portfolio_counts(engine) == PortfolioCounts(accounts=0, instruments=0, transactions=0)


def test_clearing_removes_the_instruments_source_symbols_and_quotes(engine: Engine) -> None:
    pzu = add_instrument(engine, InstrumentDraft("PZU", 2, "PLN", source_symbols={YAHOO: "PZU.WA"}))
    save_quote(engine, pzu.id, Quote(Decimal("45.12"), "PLN", date(2026, 10, 9), YAHOO), datetime(2026, 10, 9, 18))

    clear_portfolio(engine)
    # SQLite gives the next Instrument the freed id again
    again = add_instrument(engine, InstrumentDraft("PZU", 2, "PLN"))

    assert again.source_symbols == {}
    assert latest_quotes(engine) == {}


def test_clearing_restores_the_default_asset_classes_in_order(engine: Engine) -> None:
    _fill(engine)

    clear_portfolio(engine)

    assert [c.name for c in list_asset_classes(engine)] == DEFAULT_ASSET_CLASSES


def test_clearing_restores_the_default_fallback_orders(engine: Engine) -> None:
    for asset_class in list_asset_classes(engine):
        set_fallback_order(engine, asset_class.id, [YAHOO])

    clear_portfolio(engine)

    assert {c.name: c.fallback_order for c in list_asset_classes(engine)} == {
        name: default_fallback_order(name) for name in DEFAULT_ASSET_CLASSES
    }
    assert list_asset_classes(engine)[1].fallback_order == (BOSSA, YAHOO)  # Akcje polskie


def test_default_asset_classes_match_the_ones_a_new_database_starts_with(engine: Engine) -> None:
    assert [c.name for c in list_asset_classes(engine)] == DEFAULT_ASSET_CLASSES


def _fill_every_removed_table(engine: Engine) -> None:
    _fill(engine)
    pzu = add_instrument(engine, InstrumentDraft("PZU", 2, "PLN", source_symbols={YAHOO: "PZU.WA"}))
    save_quote(engine, pzu.id, Quote(Decimal("45.12"), "PLN", date(2026, 10, 9), YAHOO), datetime(2026, 10, 9, 18))
    account_id = list_accounts(engine)[0].id
    with Session(engine) as session, session.begin():
        strategy = StrategyRow(account_id=account_id)
        session.add(strategy)
        session.flush()
        session.add_all(
            [
                ClassTargetRow(strategy_id=strategy.id, asset_class_id=2, percent="100", band="5"),
                InstrumentTargetRow(strategy_id=strategy.id, instrument_id=pzu.id, percent="100"),
                BenchmarkRow(kind="account", account_id=account_id, offset="0", shown=True, position=0),
                QuoteHistoryRow(instrument_id=pzu.id, first_day=date(2026, 1, 2), last_day=date(2026, 10, 9)),
                PriceFailureRow(instrument_id=pzu.id, source=YAHOO, position=0, reason="timeout"),
                MultiAssetShareRow(instrument_id=pzu.id, asset_class_id=2, percent="100"),
                RateCorrectionRow(instrument_id=pzu.id, margin="1.5"),
                SkippedBrokerRow(external_id="xtb-1", skipped_on=date(2026, 10, 9)),
                ValuationSnapshotRow(
                    taken_on=date(2026, 10, 9),
                    taken_at=datetime(2026, 10, 9, 18),
                    account_id=account_id,
                    value="1000",
                    net_deposits="1000",
                ),
                InvestmentGoalRow(
                    account_id=account_id, mode="amount", amount="1000", withdrawal_rate="4", real_return="4"
                ),
                RecurringRuleRow(
                    id=1,
                    name="Wpłata",
                    account_id=account_id,
                    transaction_type="deposit",
                    amount="1000",
                    currency="PLN",
                    frequency="monthly",
                    day_of_month=10,
                    start_date=date(2026, 1, 1),
                    active=True,
                ),
            ]
        )
        session.flush()
        session.add(RecurringRuleSkipRow(rule_id=1, occurrence_date=date(2026, 1, 12)))


def _rows(engine: Engine, models: list[type[Base]]) -> dict[str, int]:
    with Session(engine) as session:
        return {m.__tablename__: session.scalar(select(func.count()).select_from(m)) or 0 for m in models}


def test_clearing_empties_every_table_it_removes(engine: Engine) -> None:
    # The Asset Classes are removed too, then their defaults come back
    removed = [
        m.class_ for m in Base.registry.mappers if m.class_.on_clear is OnClear.DELETE and m.class_ is not AssetClassRow
    ]
    _fill_every_removed_table(engine)
    assert 0 not in _rows(engine, removed).values()

    clear_portfolio(engine)

    assert _rows(engine, removed) == dict.fromkeys((m.__tablename__ for m in removed), 0)


def test_clearing_keeps_the_nbp_rate_cache(engine: Engine) -> None:
    rate = NbpRate("USD", Decimal("4.0123"), date(2024, 1, 2), "001/A/NBP/2024")
    cache_rate(engine, date(2024, 1, 3), rate)

    clear_portfolio(engine)

    assert cached_rate(engine, "USD", date(2024, 1, 3)) == rate


def test_clearing_backs_up_the_database_first(engine: Engine, db_file: Path) -> None:
    _fill(engine)

    backup = clear_portfolio(engine)

    assert backup is not None
    assert backup.parent == db_file.parent / "backups"
    restored = init_db(backup)
    assert [a.name for a in list_accounts(restored)] == ["XTB"]
    assert len(list_transactions(restored)) == 2


def test_a_cleared_portfolio_accepts_new_data(engine: Engine) -> None:
    _fill(engine)
    clear_portfolio(engine)

    _fill(engine)

    assert portfolio_counts(engine) == PortfolioCounts(accounts=1, instruments=1, transactions=2)


def test_a_failed_backup_clears_nothing(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    _fill(engine)

    def locked(db_path: Path, backups_dir: Path) -> Path:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(reset, "backup_database", locked)

    with pytest.raises(BackupError, match="kopii zapasowej"):
        clear_portfolio(engine)
    assert portfolio_counts(engine) == PortfolioCounts(accounts=1, instruments=1, transactions=2)


def test_every_model_declares_whether_clearing_removes_it() -> None:
    undeclared = [m.class_.__name__ for m in Base.registry.mappers if "on_clear" not in vars(m.class_)]

    assert undeclared == []


def test_clearing_keeps_the_rate_caches_the_bond_data_the_settings_and_the_contribution_limits() -> None:
    kept = {m.class_.__tablename__ for m in Base.registry.mappers if m.class_.on_clear is OnClear.KEEP}

    assert kept == {
        "nbp_rates",
        "nbp_rate_history",
        "nbp_history",
        "mf_bond_series",
        "cpi",
        "nbp_reference_rates",
        "bond_data_status",
        "app_settings",
        "contribution_limits",
    }


def test_a_database_without_a_file_is_not_cleared() -> None:
    engine = create_engine("sqlite://")

    with pytest.raises(BackupError, match="Nie znaleziono pliku bazy"):
        clear_portfolio(engine)
