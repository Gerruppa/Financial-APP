"""The XTB import and its Reconciliation with the Transactions entered, on a database (L-17, spec 7)."""

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.lots import InsufficientQuantityError
from financial_app.domain.reconciliation import Choice
from financial_app.domain.transactions import (
    Origin,
    Transaction,
    TransactionDraft,
    TransactionType,
    buy_or_sell,
    cash_transfer,
    cost,
)
from financial_app.domain.xtb_import import XtbError
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.reset import clear_portfolio
from financial_app.persistence.settings import load_setting
from financial_app.persistence.transactions import add_transactions, list_transactions
from financial_app.sources.xtb import XtbDecisions, apply_xtb, preview_xtb, read_statements
from xtb_rows import op, write_statement

IKE_NUMBER = "54925231"
MAIN_NUMBER = "54864339"
TODAY = date(2026, 10, 13)


class FixedNbp:
    def before(self, currency: str, day: date) -> NbpRate:
        assert currency == "USD"
        return NbpRate("USD", Decimal("3.7000"), date(2026, 7, 29), "145/A/NBP/2026")


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def ike(engine: Engine) -> int:
    return add_account(engine, AccountDraft("IKE", "Arkusz", AccountType.IKE, ("PLN",))).id


@pytest.fixture
def isac(engine: Engine) -> int:
    etf = next(c for c in list_asset_classes(engine) if c.name == "Akcje zagraniczne")
    return add_instrument(engine, InstrumentDraft("ISAC", etf.id, "USD")).id


def ike_statement(tmp_path: Path) -> Path:
    return write_statement(
        tmp_path / "IKE.xlsx",
        IKE_NUMBER,
        [
            op("IKE deposit", datetime(2026, 7, 30, 6, 49), 6000.0, "100",
               "Transfer in operation on account with id 1"),
            op("Stock purchase", datetime(2026, 7, 30, 9, 52), -5000.0, "101", "OPEN BUY 15 @ 90.00", "ISAC.UK",
               "MSCI ACWI", "9"),
            op("Free funds interest", datetime(2026, 8, 4, 17, 36), 0.25, "102", "Free-funds Interest 2026-07"),
        ],
    )  # fmt: skip


def entered(engine: Engine, ike: int, isac: int) -> list[Transaction]:
    nbp = FixedNbp().before("USD", date(2026, 7, 30))
    buy = buy_or_sell(ike, date(2026, 7, 30), TransactionType.BUY, isac, Decimal(15), Decimal(90), nbp_rate=nbp)
    deposit = TransactionDraft(ike, date(2026, 7, 30), TransactionType.DEPOSIT, Decimal(7100))
    return add_transactions(
        engine,
        [replace(deposit, origin=Origin.SPREADSHEET, external_id="sheet-1"), replace(buy, comment="IKE MSCI ACWI")],
    )


def test_the_ike_account_is_suggested_and_the_ticker_matched_by_name(
    engine: Engine, ike: int, isac: int, tmp_path: Path
) -> None:
    statements = read_statements(ike_statement(tmp_path))
    preview = preview_xtb(engine, statements, FixedNbp(), XtbDecisions())
    assert preview.accounts == {IKE_NUMBER: ike}
    assert not preview.blocked
    assert len(preview.reconciliation.broker_only) == 3


def test_the_broker_is_the_source_of_truth_by_default(engine: Engine, ike: int, isac: int, tmp_path: Path) -> None:
    deposit, buy = entered(engine, ike, isac)
    statements = read_statements(ike_statement(tmp_path))
    preview = preview_xtb(engine, statements, FixedNbp(), XtbDecisions())
    assert [pair.mine.id for pair in preview.reconciliation.different] == [buy.id]
    assert [t.id for t in preview.reconciliation.mine_only] == [deposit.id]
    assert [d.actual_amount for d in preview.reconciliation.broker_only] == [Decimal(6000), Decimal("0.25")]

    apply_xtb(engine, statements, FixedNbp(), XtbDecisions(), TODAY)

    saved = {t.id: t for t in list_transactions(engine)}
    assert deposit.id not in saved
    assert saved[buy.id].actual_amount == Decimal("5000.00")
    assert saved[buy.id].comment == "IKE MSCI ACWI"  # the user's comment stays
    assert saved[buy.id].origin is Origin.BROKER
    assert sorted(t.actual_amount for t in saved.values()) == [Decimal("0.25"), Decimal("5000.00"), Decimal(6000)]
    assert load_setting(engine, "xtb_account:" + IKE_NUMBER) == str(ike)

    again = preview_xtb(engine, statements, FixedNbp(), XtbDecisions())
    assert again.handled == 3
    assert (again.reconciliation.pairs, again.reconciliation.broker_only, again.reconciliation.mine_only) == (
        [],
        [],
        [],
    )


def test_keeping_mine_and_skipping_the_brokers_are_remembered(
    engine: Engine, ike: int, isac: int, tmp_path: Path
) -> None:
    deposit, buy = entered(engine, ike, isac)
    statements = read_statements(ike_statement(tmp_path))
    preview = preview_xtb(engine, statements, FixedNbp(), XtbDecisions())
    choices = {key: Choice.MINE for key in ["xtb-100", "xtb-101", "xtb-102", f"mine-{deposit.id}"]}
    apply_xtb(engine, statements, FixedNbp(), XtbDecisions(choices=choices), TODAY)

    assert list_transactions(engine) == [buy, deposit]
    again = preview_xtb(engine, statements, FixedNbp(), XtbDecisions())
    assert again.handled == 3
    assert again.reconciliation.mine_only == []
    assert preview.reconciliation.pairs[0].key == "xtb-101"


def test_nothing_is_saved_when_a_sell_would_lose_its_cover(engine: Engine, ike: int, isac: int, tmp_path: Path) -> None:
    nbp = FixedNbp().before("USD", date(2026, 7, 30))
    buy = buy_or_sell(ike, date(2026, 7, 30), TransactionType.BUY, isac, Decimal(10), Decimal(90), nbp_rate=nbp)
    sell = buy_or_sell(ike, date(2026, 8, 1), TransactionType.SELL, isac, Decimal(10), Decimal(95), nbp_rate=nbp)
    buy, sell = add_transactions(engine, [buy, sell])
    statements = read_statements(ike_statement(tmp_path))
    # The entered Buy (another quantity than XTB's) goes, the entered Sell stays and XTB's Buy is skipped
    choices = {f"mine-{sell.id}": Choice.MINE, "xtb-101": Choice.MINE}
    preview = preview_xtb(engine, statements, FixedNbp(), XtbDecisions(choices=choices))
    assert [t.id for t in preview.reconciliation.mine_only] == [buy.id, sell.id]
    with pytest.raises(InsufficientQuantityError):
        apply_xtb(engine, statements, FixedNbp(), XtbDecisions(choices=choices), TODAY)
    assert list_transactions(engine) == [sell, buy]
    assert preview_xtb(engine, statements, FixedNbp(), XtbDecisions()).handled == 0


def test_an_unmatched_ticker_blocks_applying(engine: Engine, ike: int, tmp_path: Path) -> None:
    statements = read_statements(ike_statement(tmp_path))
    preview = preview_xtb(engine, statements, FixedNbp(), XtbDecisions())
    assert preview.unmatched_tickers == {"ISAC.UK": "MSCI ACWI"}
    with pytest.raises(XtbError, match="instrument"):
        apply_xtb(engine, statements, FixedNbp(), XtbDecisions(), TODAY)


def test_a_left_out_account_turns_the_transfer_into_a_deposit(engine: Engine, ike: int, tmp_path: Path) -> None:
    main = add_account(engine, AccountDraft("XTB", "XTB", AccountType.REGULAR, ("PLN",))).id
    folder = tmp_path / "xtb"
    folder.mkdir()
    write_statement(
        folder / "PLN.xlsx",
        MAIN_NUMBER,
        [op("IKE deposit", datetime(2026, 7, 30, 6, 49), -6000.0, "99", "Transfer out operation on account with id 2")],
        product="My Trades",
    )
    write_statement(
        folder / "IKE.xlsx",
        IKE_NUMBER,
        [op("IKE deposit", datetime(2026, 7, 30, 6, 49), 6000.0, "100", "Transfer in operation on account with id 1")],
    )
    statements = read_statements(folder)
    both = preview_xtb(engine, statements, FixedNbp(), XtbDecisions(accounts={MAIN_NUMBER: main}))
    [transfer] = both.reconciliation.broker_only
    assert (transfer.transaction_type, transfer.account_id, transfer.target_account_id) == (
        TransactionType.CASH_TRANSFER,
        main,
        ike,
    )
    ike_only = preview_xtb(engine, statements, FixedNbp(), XtbDecisions(accounts={MAIN_NUMBER: None}))
    [deposit] = ike_only.reconciliation.broker_only
    assert (deposit.transaction_type, deposit.account_id) == (TransactionType.DEPOSIT, ike)

    apply_xtb(engine, statements, FixedNbp(), XtbDecisions(accounts={MAIN_NUMBER: None}), TODAY)
    assert load_setting(engine, "xtb_account:" + MAIN_NUMBER) == "skip"
    assert preview_xtb(engine, statements, FixedNbp(), XtbDecisions()).accounts[MAIN_NUMBER] is None


def test_clearing_the_data_forgets_the_matches(engine: Engine, ike: int, isac: int, tmp_path: Path) -> None:
    statements = read_statements(ike_statement(tmp_path))
    apply_xtb(engine, statements, FixedNbp(), XtbDecisions(instruments={"ISAC.UK": isac}), TODAY)
    assert load_setting(engine, "xtb_ticker:ISAC.UK") == str(isac)
    clear_portfolio(engine)
    assert load_setting(engine, "xtb_ticker:ISAC.UK") is None
    assert load_setting(engine, "xtb_account:" + IKE_NUMBER) is None


def test_what_xtb_cannot_show_is_never_offered_for_deleting(
    engine: Engine, ike: int, isac: int, tmp_path: Path
) -> None:
    fee = add_transactions(engine, [cost(ike, date(2026, 7, 31), Decimal(5))])
    statements = read_statements(ike_statement(tmp_path))
    preview = preview_xtb(engine, statements, FixedNbp(), XtbDecisions())
    assert preview.reconciliation.mine_only == []
    apply_xtb(engine, statements, FixedNbp(), XtbDecisions(), TODAY)
    assert fee[0] in list_transactions(engine)


def test_a_transfer_entered_from_a_bank_is_xtbs_deposit_and_stays(
    engine: Engine, ike: int, isac: int, tmp_path: Path
) -> None:
    bank = add_account(engine, AccountDraft("Bank", "mBank", AccountType.REGULAR, ("PLN",))).id
    [transfer] = add_transactions(engine, [cash_transfer(bank, date(2026, 7, 30), ike, Decimal(6000))])
    statements = read_statements(ike_statement(tmp_path))
    preview = preview_xtb(engine, statements, FixedNbp(), XtbDecisions())
    [pair] = preview.reconciliation.same
    assert (pair.mine, pair.linked) == (transfer, True)
    apply_xtb(engine, statements, FixedNbp(), XtbDecisions(), TODAY)
    assert transfer in list_transactions(engine)
    assert not any(t.transaction_type is TransactionType.DEPOSIT for t in list_transactions(engine))
    assert preview_xtb(engine, statements, FixedNbp(), XtbDecisions()).reconciliation.pairs == []


def test_an_account_in_another_currency_is_refused(tmp_path: Path) -> None:
    path = write_statement(tmp_path / "USD.xlsx", "1", [])
    book = openpyxl.load_workbook(path)
    positions = book["Open Positions"]
    positions.append(["Product", "Metric", "Amount", "Currency"])
    positions.append(["My Trades", "Open position value", 0.0, "USD"])
    book.save(path)
    with pytest.raises(XtbError, match="USD"):
        read_statements(path)
