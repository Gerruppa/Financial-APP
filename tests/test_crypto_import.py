"""The Binance, OKX and Trezor CSV import on a database (spec 7)."""

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
from financial_app.domain.transactions import Origin, TransactionType, lowest_cash_balance
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.reset import clear_portfolio
from financial_app.persistence.settings import CRYPTO_ACCOUNT, CRYPTO_WALLET, load_setting
from financial_app.persistence.transactions import list_transactions
from financial_app.sources.crypto import (
    CryptoDecisions,
    CryptoFile,
    CryptoPreview,
    apply_crypto,
    preview_crypto,
    proposed_deposits,
    read_crypto,
)

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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8-sig")
    return path


def read_one(path: Path) -> list[CryptoFile]:
    files = read_crypto(path)
    assert len(files) == 1
    return files


def preview_one(engine: Engine, files: list[CryptoFile], decisions: CryptoDecisions) -> CryptoPreview:
    (preview,) = preview_crypto(engine, files, FixedNbp(), prices, decisions)
    return preview


def test_binance_trades_are_priced_from_the_market(engine: Engine, account: int, bitcoin: int, tmp_path: Path) -> None:
    files = read_one(write(tmp_path, "binance.csv", BINANCE))
    decisions = CryptoDecisions({"binance": account})
    preview = preview_one(engine, files, decisions)
    assert not preview.blocked
    # The Instrument was found by its Yahoo symbol, so nothing was chosen
    assert [d.actual_amount for d in preview.drafts] == [Decimal("2000.00"), Decimal("800.00")]
    apply_crypto(engine, files, FixedNbp(), prices, decisions, TODAY)
    saved = [t for t in list_transactions(engine) if t.transaction_type is not TransactionType.DEPOSIT]
    assert [(t.transaction_type, t.quantity, t.origin) for t in sorted(saved, key=lambda t: t.date)] == [
        (TransactionType.BUY, Decimal("0.01"), Origin.BROKER),
        (TransactionType.SELL, Decimal("0.004"), Origin.BROKER),
    ]
    assert load_setting(engine, CRYPTO_ACCOUNT + "binance") == str(account)


def test_deposits_are_proposed_where_purchases_take_the_cash_below_zero(
    engine: Engine, account: int, bitcoin: int, tmp_path: Path
) -> None:
    files = read_one(write(tmp_path, "binance.csv", BINANCE))
    # Declined for the Account: the purchase leaves its cash at -2000
    declined = CryptoDecisions({"binance": account}, no_deposits=frozenset({account}))
    apply_crypto(engine, files, FixedNbp(), prices, declined, TODAY)
    assert lowest_cash_balance(list_transactions(engine), account, start=date(2026, 1, 1)) == Decimal("-2000.00")

    # Nothing is left to import, but the history already saved still lacks its deposit
    decisions = CryptoDecisions({"binance": account})
    previews = preview_crypto(engine, files, FixedNbp(), prices, decisions)
    proposed = proposed_deposits(engine, previews)
    assert [(d.account_id, d.date, d.actual_amount) for d in proposed[account]] == [
        (account, date(2026, 1, 5), Decimal("2000.00"))
    ]
    apply_crypto(engine, files, FixedNbp(), prices, decisions, TODAY)
    assert lowest_cash_balance(list_transactions(engine), account, start=date(2026, 1, 1)) == 0
    assert proposed_deposits(engine, preview_crypto(engine, files, FixedNbp(), prices, decisions)) == {}


def test_the_same_file_is_not_imported_twice(engine: Engine, account: int, bitcoin: int, tmp_path: Path) -> None:
    files = read_one(write(tmp_path, "binance.csv", BINANCE))
    apply_crypto(engine, files, FixedNbp(), prices, CryptoDecisions({"binance": account}), TODAY)
    again = preview_one(engine, files, CryptoDecisions({"binance": account}))
    assert (again.drafts, again.handled) == ([], 2)


def test_the_account_and_coin_must_be_chosen(engine: Engine, tmp_path: Path) -> None:
    files = read_one(write(tmp_path, "okx.csv", OKX))
    preview = preview_one(engine, files, CryptoDecisions())
    assert preview.blocked
    assert (preview.account_id, preview.unmatched_coins) == (None, ["BTC"])
    with pytest.raises(CryptoError, match="Wybierz"):
        apply_crypto(engine, files, FixedNbp(), prices, CryptoDecisions(), TODAY)
    assert list_transactions(engine) == []


def test_a_price_that_cannot_be_fetched_blocks_without_saving(
    engine: Engine, account: int, bitcoin: int, tmp_path: Path
) -> None:
    def no_price(symbol: str, currency: str, day: date) -> Decimal:
        raise CryptoError("Yahoo nie podaje ceny.")

    files = read_one(write(tmp_path, "binance.csv", BINANCE))
    decisions = CryptoDecisions({"binance": account})
    (preview,) = preview_crypto(engine, files, FixedNbp(), no_price, decisions)
    assert preview.blocked
    with pytest.raises(CryptoError, match="Yahoo"):
        apply_crypto(engine, files, FixedNbp(), no_price, decisions, TODAY)
    assert list_transactions(engine) == []


def test_a_folder_takes_the_exact_quantity_from_trade_details(
    engine: Engine, account: int, bitcoin: int, tmp_path: Path
) -> None:
    folder = tmp_path / "okx"
    write(folder, "Order History.csv", OKX)
    # The order says 0.003 BTC (rounded); the fill is worth 0.0034 BTC
    fill = "9,1,2026-10-15 14:54:57,Spot,BTC-USDC,0.003,BTC,100000,USDC,340,USDC,taker,0,BTC\n"
    write(folder, "Trade Details.csv", "UID:1,Account Type:Main\n" + TRADES + fill)
    files = read_one(folder)
    assert (files[0].exchange, len(files[0].trades), files[0].unsupported) == ("okx", 1, [])
    apply_crypto(engine, files, FixedNbp(), prices, CryptoDecisions({"okx": account}), TODAY)
    (saved,) = [t for t in list_transactions(engine) if t.transaction_type is TransactionType.BUY]
    assert saved.quantity == Decimal("0.0034")
    assert saved.actual_amount == Decimal("1360.00")  # 0.0034 x 100000 USD x 4.0


def test_a_file_of_neither_exchange_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CryptoError, match="Binance, OKX ani Trezora"):
        read_crypto(write(tmp_path, "other.csv", "a,b\n1,2\n"))
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(CryptoError, match="nie ma plików"):
        read_crypto(empty)


def test_clearing_the_data_forgets_the_remembered_matches(
    engine: Engine, account: int, bitcoin: int, tmp_path: Path
) -> None:
    files = read_one(write(tmp_path, "binance.csv", BINANCE))
    apply_crypto(engine, files, FixedNbp(), prices, CryptoDecisions({"binance": account}), TODAY)
    clear_portfolio(engine)
    assert load_setting(engine, CRYPTO_ACCOUNT + "binance") is None


WITHDRAWAL = (
    BINANCE
    + "1,2026-03-01 10:00:00,Spot,Withdraw,BTC,-0.005,Withdraw fee is included\n"
    + "1,2026-03-01 10:00:00,Spot,Withdraw,BTC,-0.0001,Withdraw fee is included\n"
)


def test_a_withdrawal_moves_the_lots_to_the_wallet_account(
    engine: Engine, account: int, bitcoin: int, tmp_path: Path
) -> None:
    wallet = add_account(engine, AccountDraft("Portfel BTC", "Zimny", AccountType.REGULAR, ("PLN",))).id
    files = read_one(write(tmp_path, "binance.csv", WITHDRAWAL))
    blocked = preview_one(engine, files, CryptoDecisions({"binance": account}))
    assert blocked.needs_wallet and blocked.blocked
    with pytest.raises(CryptoError, match="portfela"):
        apply_crypto(engine, files, FixedNbp(), prices, CryptoDecisions({"binance": account}), TODAY)
    assert list_transactions(engine) == []

    decisions = CryptoDecisions({"binance": account}, {"binance": wallet})
    apply_crypto(engine, files, FixedNbp(), prices, decisions, TODAY)
    kinds = [(t.transaction_type, t.account_id, t.target_account_id) for t in list_transactions(engine)]
    assert (TransactionType.SECURITY_TRANSFER, account, wallet) in kinds
    # The network fee (0.0001 BTC x 50000 USD x 4.0 = 20 PLN) is a sale of the coins that is all commission
    (fee,) = [t for t in list_transactions(engine) if t.external_id and "-fee-" in t.external_id]
    assert (fee.transaction_type, fee.account_id, fee.quantity, fee.commission) == (
        TransactionType.SELL,
        account,
        Decimal("0.0001"),
        Decimal("19.99"),
    )
    # The wallet is remembered, and the withdrawal and its fee are not offered again
    again = preview_one(engine, files, CryptoDecisions({"binance": account}))
    assert (again.drafts, again.handled, again.wallet_id) == ([], 4, None)
    assert load_setting(engine, CRYPTO_WALLET + "binance") == str(wallet)


OKX_FUNDING = (
    "UID:1,Account Type:Main,Time Zone:UTC+8\n"
    "id,Time,Type,Amount,Before Balance,After Balance,Symbol,Amount-USD\n"
    "5,2026-10-14 20:00:00,Deposit,0.001,0,0.001,BTC,100\n"
    "6,2026-10-14 20:00:00,To unified trading account,-0.001,0.001,0,BTC,-100\n"
)


def test_okx_deposits_from_the_wallet_fund_a_later_sale(
    engine: Engine, account: int, bitcoin: int, tmp_path: Path
) -> None:
    wallet = add_account(engine, AccountDraft("Portfel BTC", "Zimny", AccountType.REGULAR, ("PLN",))).id
    okx = add_account(engine, AccountDraft("OKX", "Krypto", AccountType.REGULAR, ("PLN",))).id
    binance = read_one(write(tmp_path, "binance.csv", WITHDRAWAL))
    apply_crypto(engine, binance, FixedNbp(), prices, CryptoDecisions({"binance": account}, {"binance": wallet}), TODAY)
    folder = tmp_path / "okx"
    sale = (
        "10,2026-10-16 10:00:00,Spot,BTC-USDC,0,Sell,MARKET,0.0044,0.0044,USDC,100000,100000,USDC,0,0,USDC,COMPLETE,\n"
    )
    write(folder, "Order History.csv", OKX + sale)
    fills = (
        "9,1,2026-10-15 14:54:57,Spot,BTC-USDC,0.003,BTC,100000,USDC,340,USDC,taker,0,BTC\n"
        "10,2,2026-10-16 10:00:00,Spot,BTC-USDC,0.0044,BTC,100000,USDC,440,USDC,taker,0,USDC\n"
    )
    write(folder, "Trade Details.csv", "UID:1,Account Type:Main\n" + TRADES + fills)
    write(folder, "OKX Funding History.csv", OKX_FUNDING)

    files = read_one(folder)
    assert [(t.symbol, t.quantity, t.incoming) for t in files[0].transfers] == [("BTC", Decimal("0.001"), True)]
    apply_crypto(engine, files, FixedNbp(), prices, CryptoDecisions({"okx": okx}, {"okx": wallet}), TODAY)
    deposit = next(t for t in list_transactions(engine) if t.external_id == "okx-funding-5")
    assert (deposit.account_id, deposit.target_account_id, deposit.date) == (wallet, okx, date(2026, 10, 14))


TREZOR_HEADER = (
    "Timestamp,Date,Time,Type,Transaction ID,Fee,Fee unit,Address,Label,Amount,Amount unit,Fiat (USD),Other\n"
)
TREZOR = (
    TREZOR_HEADER
    # 1 March 2026, 12:00 UTC: what the Binance withdrawal brought, less what the exchange counted in
    + "1772366400,01.03.2026,13:00:00 GMT+1,RECV,r1,,,bc1q,,0.00499,BTC,250,\n"
    # 1 and 10 April: a receipt and a send no saved transfer explains
    + "1775044800,01.04.2026,14:00:00 GMT+2,RECV,r2,,,bc1q,,0.0005,BTC,30,\n"
    + "1775822400,10.04.2026,14:00:00 GMT+2,SENT,s1,0.00001,BTC,3x,,0.001,BTC,60,\n"
)


def test_trezor_pairs_its_receipt_with_the_exchange_withdrawal_and_leaves_the_rest_for_later(
    engine: Engine, account: int, bitcoin: int, tmp_path: Path
) -> None:
    wallet = add_account(engine, AccountDraft("Trezor", "Zimny", AccountType.REGULAR, ("PLN",))).id
    binance = read_one(write(tmp_path, "binance.csv", WITHDRAWAL))
    apply_crypto(engine, binance, FixedNbp(), prices, CryptoDecisions({"binance": account}, {"binance": wallet}), TODAY)
    withdrawal = next(t for t in list_transactions(engine) if t.transaction_type is TransactionType.SECURITY_TRANSFER)
    files = read_one(write(tmp_path, "trezor.csv", TREZOR))
    assert files[0].exchange == "trezor"

    # The wallet the exchange's withdrawals went to is the Trezor's Account unless another is chosen
    preview = preview_one(engine, files, CryptoDecisions())
    assert preview.account_id == wallet and preview.pairs == {"trezor-r1": withdrawal}
    # A transfer with no other Account chosen is left for a later import, and blocks nothing
    assert [t.external_id for t in preview.later] == ["trezor-r2", "trezor-s1"] and not preview.blocked
    # The wallet's own Account, chosen as the other one before it became the wallet's, is no choice
    itself = preview_one(engine, files, CryptoDecisions(counterparts={"trezor-r2": wallet}))
    assert [t.external_id for t in itself.later] == ["trezor-r2", "trezor-s1"]

    decisions = CryptoDecisions(counterparts={"trezor-r2": account}, skipped=frozenset({"trezor-s1"}))
    apply_crypto(engine, files, FixedNbp(), prices, decisions, TODAY)
    added = {t.external_id: t for t in list_transactions(engine) if t.external_id and "trezor" in t.external_id}
    assert set(added) == {"trezor-r2", "trezor-s1-fee"}
    receipt, fee = added["trezor-r2"], added["trezor-s1-fee"]
    assert (receipt.account_id, receipt.target_account_id, receipt.quantity) == (account, wallet, Decimal("0.0005"))
    # The send was skipped, but its network fee left the wallet: 0.00001 BTC x 50000 USD x 4.0 = 2 PLN
    assert (fee.transaction_type, fee.account_id, fee.commission) == (TransactionType.SELL, wallet, Decimal("1.99"))
    # The paired, added and skipped rows are not offered again
    again = preview_one(engine, files, CryptoDecisions())
    assert (again.drafts, again.pairs, again.later, again.handled) == ([], {}, [], 4)
    assert load_setting(engine, CRYPTO_ACCOUNT + "trezor") == str(wallet)


# 13 October 2026, 12:00 UTC: the send whose deposit OKX booked the next day
TREZOR_SEND_TO_OKX = "1791892800,13.10.2026,14:00:00 GMT+2,SENT,s2,0.00001,BTC,3x,,0.001,BTC,60,\n"


def test_a_folder_of_every_source_imports_at_once_and_the_wallet_pairs_with_the_exchanges(
    engine: Engine, account: int, bitcoin: int, tmp_path: Path
) -> None:
    wallet = add_account(engine, AccountDraft("Trezor", "Zimny", AccountType.REGULAR, ("PLN",))).id
    okx = add_account(engine, AccountDraft("OKX", "Krypto", AccountType.REGULAR, ("PLN",))).id
    folder = tmp_path / "Krypto"
    write(folder, "Bitcoin_Trezor.csv", TREZOR + TREZOR_SEND_TO_OKX)
    write(folder, "binance.csv", WITHDRAWAL)
    # The same export twice, e.g. a backup copy in a subfolder: its rows count once
    write(folder, "kopia/binance (1).csv", WITHDRAWAL)
    write(folder, "OKX/OKX Funding History.csv", OKX_FUNDING)

    files = read_crypto(folder)
    # The exchanges come first, so the wallet's transfers find theirs among them
    assert [file.exchange for file in files] == ["binance", "okx", "trezor"]
    assert len(files[0].trades) == 3 and len(files[0].transfers) == 1
    decisions = CryptoDecisions({"binance": account, "okx": okx}, {"binance": wallet, "okx": wallet})
    binance, okx_preview, trezor = preview_crypto(engine, files, FixedNbp(), prices, decisions)
    # The Trezor's Account is the wallet both exchanges chose in this import
    assert trezor.account_id == wallet
    assert set(trezor.pairs) == {"trezor-r1", "trezor-s2"} and [t.external_id for t in trezor.later] == [
        "trezor-r2",
        "trezor-s1",
    ]

    apply_crypto(engine, files, FixedNbp(), prices, decisions, TODAY)
    transfers = [t for t in list_transactions(engine) if t.transaction_type is TransactionType.SECURITY_TRANSFER]
    # The Binance withdrawal and the OKX deposit, each once; the Trezor's own rows added none
    assert sorted(t.external_id or "" for t in transfers) == [
        "binance-2026-03-01 10:00:00-withdraw-BTC-1",
        "okx-funding-5",
    ]
    fees = [t.external_id or "" for t in list_transactions(engine) if (t.external_id or "").endswith("-fee")]
    assert sorted(fees) == ["trezor-s1-fee", "trezor-s2-fee"]
    # Paired in this import, the wallet's rows are not offered again
    again = preview_crypto(engine, files, FixedNbp(), prices, CryptoDecisions())
    assert [p.drafts for p in again] == [[], [], []]
    assert [t.external_id for t in again[2].later] == ["trezor-r2", "trezor-s1"]


def test_an_exchange_withdrawal_pairs_with_the_transfer_the_wallet_import_added_before(
    engine: Engine, account: int, bitcoin: int, tmp_path: Path
) -> None:
    wallet = add_account(engine, AccountDraft("Trezor", "Zimny", AccountType.REGULAR, ("PLN",))).id
    apply_crypto(engine, read_one(write(tmp_path, "b.csv", BINANCE)), FixedNbp(), prices,
                 CryptoDecisions({"binance": account}), TODAY)  # fmt: skip
    # The Trezor was imported first, its receipt from the exchange's Account chosen by hand
    trezor = read_one(write(tmp_path, "trezor.csv", TREZOR_HEADER + TREZOR.splitlines(keepends=True)[1]))
    apply_crypto(engine, trezor, FixedNbp(), prices,
                 CryptoDecisions({"trezor": wallet}, counterparts={"trezor-r1": account}), TODAY)  # fmt: skip

    files = read_one(write(tmp_path, "binance.csv", WITHDRAWAL))
    preview = preview_one(engine, files, CryptoDecisions({"binance": account}, {"binance": wallet}))
    assert set(preview.pairs) == {"binance-2026-03-01 10:00:00-withdraw-BTC-1"}
    apply_crypto(engine, files, FixedNbp(), prices, CryptoDecisions({"binance": account}, {"binance": wallet}), TODAY)
    transfers = [t for t in list_transactions(engine) if t.transaction_type is TransactionType.SECURITY_TRANSFER]
    assert [t.external_id for t in transfers] == ["trezor-r1"]
