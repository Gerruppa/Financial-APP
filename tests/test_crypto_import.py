"""The Binance and OKX CSV import on a database (spec 7)."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.crypto_import import CryptoError
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.prices import YAHOO
from financial_app.domain.transactions import Origin, TransactionType
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.reset import clear_portfolio
from financial_app.persistence.settings import CRYPTO_ACCOUNT, load_setting
from financial_app.persistence.transactions import list_transactions
from financial_app.sources.crypto import CryptoDecisions, apply_crypto, preview_crypto, read_crypto

TODAY = date(2026, 10, 28)
BINANCE = (
    "User ID,Time,Account,Operation,Coin,Change,Remark\n"
    "1,2026-01-05 21:53:52,Spot,Buy Crypto With Fiat,BTC,0.01,Via CashBalance\n"
    "1,2026-02-06 10:00:00,Spot,Binance Convert,BTC,-0.004,\n"
)
OKX = (
    "UID:1,Account Type:Main\n"
    "Order ID,Order Time,Instrument,Symbol,Lvg,Side,Order Type,Order Amount,Filled Amount,Amount Unit,Order Price,"
    "Avg. Filled Price,Price Unit,PNL,Fee,Fee Unit,Status,Bot ID\n"
    "9,2026-10-15 14:54:57,Spot,BTC-USDC,0,Buy,MARKET,300,0.003,USDC,100000,100000,USDC,0,0,BTC,COMPLETE,\n"
)
TRADES = (
    "Order ID,Trade ID,Trade Time,Instrument,Symbol,Filled Amount,Filled Amount Unit,Filled Price,Fill Price Unit,"
    "Trading Volume,Trading Volume Unit,taker/maker,Fee,Fee Unit\n"
)


class FixedNbp:
    def before(self, currency: str, day: date) -> NbpRate:
        assert currency == "USD"
        return NbpRate("USD", Decimal("4.0000"), day - timedelta(days=1), "145/A/NBP/2026")


def prices(symbol: str, currency: str, day: date) -> Decimal:
    assert (symbol, currency) == ("BTC-USD", "USD")
    return Decimal("50000")


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def account(engine: Engine) -> int:
    return add_account(engine, AccountDraft("Giełda", "Krypto", AccountType.REGULAR, ("PLN",))).id


@pytest.fixture
def bitcoin(engine: Engine) -> int:
    crypto = next(c for c in list_asset_classes(engine) if c.name == "Kryptowaluty")
    draft = InstrumentDraft("Bitcoin", crypto.id, "USD", source_symbols={YAHOO: "BTC-USD"}, quantity_decimals=8)
    return add_instrument(engine, draft).id


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8-sig")
    return path


def test_binance_trades_are_priced_from_the_market(engine: Engine, account: int, bitcoin: int, tmp_path: Path) -> None:
    file = read_crypto(write(tmp_path, "binance.csv", BINANCE))
    decisions = CryptoDecisions(account)
    preview = preview_crypto(engine, file, FixedNbp(), prices, decisions)
    assert not preview.blocked
    # The Instrument was found by its Yahoo symbol, so nothing was chosen
    assert [d.actual_amount for d in preview.drafts] == [Decimal("2000.00"), Decimal("800.00")]
    apply_crypto(engine, file, FixedNbp(), prices, decisions, TODAY)
    saved = list_transactions(engine)
    assert [(t.transaction_type, t.quantity, t.origin) for t in sorted(saved, key=lambda t: t.date)] == [
        (TransactionType.BUY, Decimal("0.01"), Origin.BROKER),
        (TransactionType.SELL, Decimal("0.004"), Origin.BROKER),
    ]
    assert load_setting(engine, CRYPTO_ACCOUNT + "binance") == str(account)


def test_the_same_file_is_not_imported_twice(engine: Engine, account: int, bitcoin: int, tmp_path: Path) -> None:
    file = read_crypto(write(tmp_path, "binance.csv", BINANCE))
    apply_crypto(engine, file, FixedNbp(), prices, CryptoDecisions(account), TODAY)
    again = preview_crypto(engine, file, FixedNbp(), prices, CryptoDecisions(account))
    assert (again.drafts, again.handled) == ([], 2)


def test_the_account_and_coin_must_be_chosen(engine: Engine, tmp_path: Path) -> None:
    file = read_crypto(write(tmp_path, "okx.csv", OKX))
    preview = preview_crypto(engine, file, FixedNbp(), prices, CryptoDecisions())
    assert preview.blocked
    assert (preview.account_id, preview.unmatched_coins) == (None, ["BTC"])
    with pytest.raises(CryptoError, match="Wybierz"):
        apply_crypto(engine, file, FixedNbp(), prices, CryptoDecisions(), TODAY)
    assert list_transactions(engine) == []


def test_a_price_that_cannot_be_fetched_blocks_without_saving(
    engine: Engine, account: int, bitcoin: int, tmp_path: Path
) -> None:
    def no_price(symbol: str, currency: str, day: date) -> Decimal:
        raise CryptoError("Yahoo nie podaje ceny.")

    file = read_crypto(write(tmp_path, "binance.csv", BINANCE))
    assert preview_crypto(engine, file, FixedNbp(), no_price, CryptoDecisions(account)).blocked
    with pytest.raises(CryptoError, match="Yahoo"):
        apply_crypto(engine, file, FixedNbp(), no_price, CryptoDecisions(account), TODAY)
    assert list_transactions(engine) == []


def test_a_folder_reads_order_history_and_skips_trade_details(
    engine: Engine, account: int, bitcoin: int, tmp_path: Path
) -> None:
    folder = tmp_path / "okx"
    folder.mkdir()
    write(folder, "Order History.csv", OKX)
    write(folder, "Trade Details.csv", "UID:1,Account Type:Main\n" + TRADES)
    file = read_crypto(folder)
    assert (file.exchange, len(file.trades)) == ("okx", 1)
    apply_crypto(engine, file, FixedNbp(), prices, CryptoDecisions(account), TODAY)
    (saved,) = list_transactions(engine)
    assert saved.actual_amount == Decimal("1200.00")  # 0.003 x 100000 USD x 4.0


def test_a_file_of_neither_exchange_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CryptoError, match="Binance ani OKX"):
        read_crypto(write(tmp_path, "other.csv", "a,b\n1,2\n"))
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(CryptoError, match="nie ma plików"):
        read_crypto(empty)


def test_clearing_the_data_forgets_the_remembered_matches(
    engine: Engine, account: int, bitcoin: int, tmp_path: Path
) -> None:
    file = read_crypto(write(tmp_path, "binance.csv", BINANCE))
    apply_crypto(engine, file, FixedNbp(), prices, CryptoDecisions(account), TODAY)
    clear_portfolio(engine)
    assert load_setting(engine, CRYPTO_ACCOUNT + "binance") is None
