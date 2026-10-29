"""Ustawienia > Import kryptowalut: the step-by-step import window, without a browser."""

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
from financial_app.domain.formatting import format_pln
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.prices import YAHOO
from financial_app.domain.transactions import Origin, TransactionType, buy_or_sell, lowest_cash_balance
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
TREZOR = (
    "Timestamp,Date,Time,Type,Transaction ID,Fee,Fee unit,Address,Label,Amount,Amount unit,Fiat (USD),Other\n"
    "1775044800,01.04.2026,14:00:00 GMT+2,RECV,r1,,,bc1q,,0.002,BTC,150,\n"
    "1775131200,02.04.2026,14:00:00 GMT+2,FAILED,f1,,,bc1q,,0.001,BTC,75,\n"
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


def bitcoin(engine: Engine) -> int:
    crypto = next(c for c in list_asset_classes(engine) if c.name == "Kryptowaluty")
    draft = InstrumentDraft("Bitcoin", crypto.id, "USD", source_symbols={YAHOO: "BTC-USD"}, quantity_decimals=8)
    return add_instrument(engine, draft).id


async def load(user: User, path: Path) -> None:
    """Open the import window, read its instructions and load ``path``."""
    user.find("Import").click()
    user.find(marker="crypto-open").click()
    await user.should_see(marker="crypto-step-1")
    await user.should_see("Trezor Suite")
    user.find(marker="crypto-next").click()
    await user.should_see(marker="crypto-step-2")
    user.find(marker="crypto-path").type(str(path))
    user.find(marker="crypto-load").click()
    await user.should_see(marker="crypto-step-3")


def choose(user: User, marker: str, value: object) -> None:
    user.find(marker=marker, kind=ui.select).elements.pop().set_value(value)


async def test_the_window_guides_through_the_import_and_proposes_the_missing_deposit(
    engine: Engine, user: User, tmp_path: Path
) -> None:
    account = add_account(engine, AccountDraft("OKX", "Krypto", AccountType.REGULAR, ("PLN",)))
    bitcoin(engine)
    export = tmp_path / "Order History.csv"
    export.write_text(OKX, encoding="utf-8")

    await load(user, export)
    # The Account is still to be chosen, so the next step waits
    assert not user.find(marker="crypto-next", kind=ui.button).elements.pop().enabled
    choose(user, "crypto-account", account.id)
    user.find(marker="crypto-next").click()

    # The purchase of 1 200 zł would take the Account's cash below zero: a deposit that day is proposed
    await user.should_see(marker="crypto-step-4")
    await user.should_see(marker=f"crypto-deposits-{account.id}")
    await user.should_see(f"15.10.2026: {format_pln(Decimal('1200'))}")
    user.find(marker="crypto-next").click()

    await user.should_see(marker="crypto-step-5")
    await user.should_see("OKX: Do dodania: 1, już zaimportowane: 0, nieobsługiwane: 2.")
    await user.should_see(marker="crypto-hints")
    user.find(marker="crypto-apply").click()

    saved = {t.transaction_type: t for t in list_transactions(engine)}
    buy, deposit = saved[TransactionType.BUY], saved[TransactionType.DEPOSIT]
    assert (buy.account_id, buy.origin, buy.actual_amount) == (account.id, Origin.BROKER, Decimal("1200.00"))
    assert (deposit.account_id, deposit.date, deposit.actual_amount) == (account.id, buy.date, Decimal("1200.00"))
    assert lowest_cash_balance(list_transactions(engine), account.id, start=date(2026, 1, 1)) == 0
    await user.should_see("już zaimportowane: 1")
    await user.should_see(marker="crypto-done")


async def test_a_declined_deposit_is_not_saved(engine: Engine, user: User, tmp_path: Path) -> None:
    account = add_account(engine, AccountDraft("OKX", "Krypto", AccountType.REGULAR, ("PLN",)))
    bitcoin(engine)
    export = tmp_path / "Order History.csv"
    export.write_text(OKX, encoding="utf-8")

    await load(user, export)
    choose(user, "crypto-account", account.id)
    user.find(marker="crypto-next").click()
    user.find(marker=f"crypto-deposits-{account.id}", kind=ui.checkbox).elements.pop().set_value(False)
    user.find(marker="crypto-next").click()
    user.find(marker="crypto-apply").click()

    assert [t.transaction_type for t in list_transactions(engine)] == [TransactionType.BUY]


async def test_a_trezor_receipt_without_a_pair_comes_from_the_account_chosen_for_it(
    engine: Engine, user: User, tmp_path: Path
) -> None:
    exchange = add_account(engine, AccountDraft("Giełda", "Krypto", AccountType.REGULAR, ("PLN",)))
    wallet = add_account(engine, AccountDraft("Trezor", "Zimny", AccountType.REGULAR, ("PLN",)))
    bitcoin_id = bitcoin(engine)
    rate = NbpRate("USD", Decimal("4.0000"), date(2026, 2, 27), "1/A/NBP/2026")
    buy = buy_or_sell(exchange.id, date(2026, 3, 1), TransactionType.BUY, bitcoin_id, Decimal("0.01"), Decimal("1"))
    add_transaction(engine, replace(buy, nbp_rate=rate))
    export = tmp_path / "Bitcoin_Trezor.csv"
    export.write_text(TREZOR, encoding="utf-8")

    await load(user, export)
    choose(user, "crypto-account", wallet.id)
    await user.should_see(marker="crypto-counterpart-trezor-r1")
    # Left for later until its other Account is chosen
    user.find(marker="crypto-next").click()
    await user.should_see(marker="crypto-later")
    user.find(marker="crypto-back").click()
    choose(user, "crypto-counterpart-trezor-r1", exchange.id)
    user.find(marker="crypto-next").click()
    user.find(marker="crypto-next").click()
    await user.should_see("Trezor: Do dodania: 1, już zaimportowane: 0, nieobsługiwane: 1.")
    user.find(marker="crypto-apply").click()

    receipt = next(t for t in list_transactions(engine) if t.transaction_type is TransactionType.SECURITY_TRANSFER)
    assert (receipt.account_id, receipt.target_account_id, receipt.quantity) == (
        exchange.id,
        wallet.id,
        Decimal("0.002"),
    )


async def test_a_folder_of_two_sources_is_imported_at_once_each_into_its_account(
    engine: Engine, user: User, tmp_path: Path
) -> None:
    okx = add_account(engine, AccountDraft("OKX", "Krypto", AccountType.REGULAR, ("PLN",)))
    wallet = add_account(engine, AccountDraft("Trezor", "Zimny", AccountType.REGULAR, ("PLN",)))
    bitcoin(engine)
    folder = tmp_path / "Krypto"
    (folder / "OKX").mkdir(parents=True)
    (folder / "OKX" / "Order History.csv").write_text(OKX, encoding="utf-8")
    # 20 October: what was bought on OKX moves to the Trezor
    receipt = "1792497600,20.10.2026,14:00:00 GMT+2,RECV,r1,,,bc1q,,0.002,BTC,150,\n"
    (folder / "Bitcoin_Trezor.csv").write_text(TREZOR.splitlines(keepends=True)[0] + receipt, encoding="utf-8")

    await load(user, folder)
    await user.should_see(marker="crypto-source-okx")
    await user.should_see(marker="crypto-source-trezor")
    choose(user, "crypto-account-okx", okx.id)
    choose(user, "crypto-account-trezor", wallet.id)
    choose(user, "crypto-counterpart-trezor-r1", okx.id)
    user.find(marker="crypto-next").click()
    user.find(marker="crypto-next").click()
    await user.should_see("OKX: Do dodania: 1")
    await user.should_see("Trezor: Do dodania: 1")
    user.find(marker="crypto-apply").click()

    saved = {t.transaction_type: t for t in list_transactions(engine)}
    assert saved[TransactionType.BUY].account_id == okx.id
    moved = saved[TransactionType.SECURITY_TRANSFER]
    assert (moved.account_id, moved.target_account_id, moved.quantity) == (okx.id, wallet.id, Decimal("0.002"))


async def test_a_file_that_is_not_an_export_is_refused(user: User, tmp_path: Path) -> None:
    other = tmp_path / "other.csv"
    other.write_text("a,b\n1,2\n", encoding="utf-8")
    user.find("Import").click()
    user.find(marker="crypto-open").click()
    user.find(marker="crypto-next").click()
    user.find(marker="crypto-path").type(str(other))
    user.find(marker="crypto-load").click()
    await user.should_see("nie wygląda na eksport")
    await user.should_see(marker="crypto-step-2")
    # Nothing loaded, so the next step waits
    assert not user.find(marker="crypto-next", kind=ui.button).elements.pop().enabled
