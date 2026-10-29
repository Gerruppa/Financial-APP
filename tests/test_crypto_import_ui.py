"""Ustawienia > Import z giełdy kryptowalut: choosing the Account and applying an OKX export, without a browser."""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.prices import YAHOO
from financial_app.domain.transactions import Origin, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.sources.nbp import NbpRates
from financial_app.ui.shell import build_shell

OKX = (
    "UID:1,Account Type:Main\n"
    "Order ID,Order Time,Instrument,Symbol,Lvg,Side,Order Type,Order Amount,Filled Amount,Amount Unit,Order Price,"
    "Avg. Filled Price,Price Unit,PNL,Fee,Fee Unit,Status,Bot ID\n"
    "9,2026-10-15 14:54:57,Spot,BTC-USDC,0,Buy,MARKET,300,0.003,USDC,100000,100000,USDC,0,0,BTC,COMPLETE,\n"
    "8,2026-10-14 10:00:00,Swap,BTC-USDT-SWAP,3,Buy,MARKET,1,1,USDT,1,1,USDT,0,0,USDT,COMPLETE,\n"
)


class FixedNbp(NbpRates):
    def __init__(self, engine: Engine) -> None:
        super().__init__(engine, fetch=lambda url: None, today=lambda: date(2026, 10, 28))

    def before(self, currency: str, day: date) -> NbpRate:
        return NbpRate(currency, Decimal("4.0000"), date(2026, 10, 14), "200/A/NBP/2026")


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
async def user(engine: Engine) -> AsyncIterator[User]:
    async with user_simulation(lambda: build_shell(engine, FixedNbp(engine))) as user:
        await user.open("/ustawienia")
        yield user


async def test_choosing_the_account_then_applying_adds_the_order(engine: Engine, user: User, tmp_path: Path) -> None:
    account = add_account(engine, AccountDraft("OKX", "Krypto", AccountType.REGULAR, ("PLN",)))
    crypto = next(c for c in list_asset_classes(engine) if c.name == "Kryptowaluty")
    add_instrument(engine, InstrumentDraft("Bitcoin", crypto.id, "USD", source_symbols={YAHOO: "BTC-USD"}))
    export = tmp_path / "Order History.csv"
    export.write_text(OKX, encoding="utf-8")

    user.find("Import").click()
    user.find(marker="crypto-path").type(str(export))
    user.find(marker="crypto-load").click()
    await user.should_see(marker="crypto-account")
    await user.should_not_see(marker="crypto-apply")

    user.find(marker="crypto-account", kind=ui.select).elements.pop().set_value(account.id)
    await user.should_see("Do dodania: 1, już zaimportowane: 0, nieobsługiwane: 2.")
    user.find(marker="crypto-apply").click()

    (saved,) = list_transactions(engine)
    assert (saved.transaction_type, saved.account_id, saved.origin) == (
        TransactionType.BUY,
        account.id,
        Origin.BROKER,
    )
    assert saved.actual_amount == Decimal("1200.00")
    await user.should_see("już zaimportowane: 1")


TREZOR = (
    "Timestamp,Date,Time,Type,Transaction ID,Fee,Fee unit,Address,Label,Amount,Amount unit,Fiat (USD),Other\n"
    "1775044800,01.04.2026,14:00:00 GMT+2,RECV,r1,,,bc1q,,0.002,BTC,150,\n"
    "1775131200,02.04.2026,14:00:00 GMT+2,FAILED,f1,,,bc1q,,0.001,BTC,75,\n"
)


async def test_a_trezor_receipt_without_a_pair_comes_from_the_account_chosen_for_it(
    engine: Engine, user: User, tmp_path: Path
) -> None:
    exchange = add_account(engine, AccountDraft("Giełda", "Krypto", AccountType.REGULAR, ("PLN",)))
    wallet = add_account(engine, AccountDraft("Trezor", "Zimny", AccountType.REGULAR, ("PLN",)))
    crypto = next(c for c in list_asset_classes(engine) if c.name == "Kryptowaluty")
    draft = InstrumentDraft("Bitcoin", crypto.id, "USD", source_symbols={YAHOO: "BTC-USD"}, quantity_decimals=8)
    bitcoin = add_instrument(engine, draft)
    rate = NbpRate("USD", Decimal("4.0000"), date(2026, 2, 27), "1/A/NBP/2026")
    buy = buy_or_sell(exchange.id, date(2026, 3, 1), TransactionType.BUY, bitcoin.id, Decimal("0.01"), Decimal("1"))
    add_transaction(engine, replace(buy, nbp_rate=rate))
    export = tmp_path / "Bitcoin_Trezor.csv"
    export.write_text(TREZOR, encoding="utf-8")

    user.find("Import").click()
    user.find(marker="crypto-path").type(str(export))
    user.find(marker="crypto-load").click()
    user.find(marker="crypto-account", kind=ui.select).elements.pop().set_value(wallet.id)
    await user.should_see(marker="crypto-counterpart-trezor-r1")
    await user.should_not_see(marker="crypto-apply")

    user.find(marker="crypto-counterpart-trezor-r1", kind=ui.select).elements.pop().set_value(exchange.id)
    await user.should_see("Do dodania: 1, już zaimportowane: 0, nieobsługiwane: 1.")
    user.find(marker="crypto-apply").click()

    receipt = next(t for t in list_transactions(engine) if t.transaction_type is TransactionType.SECURITY_TRANSFER)
    assert (receipt.account_id, receipt.target_account_id, receipt.quantity) == (
        exchange.id,
        wallet.id,
        Decimal("0.002"),
    )
    await user.should_see("już zaimportowane: 1")


async def test_a_file_that_is_not_an_export_is_refused(user: User, tmp_path: Path) -> None:
    other = tmp_path / "other.csv"
    other.write_text("a,b\n1,2\n", encoding="utf-8")
    user.find("Import").click()
    user.find(marker="crypto-path").type(str(other))
    user.find(marker="crypto-load").click()
    await user.should_see("nie wygląda na eksport")
