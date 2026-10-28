"""Reading Binance and OKX CSV exports into crypto trades and Transaction drafts (pure, no files)."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.crypto_import import (
    BINANCE,
    OKX,
    CryptoContext,
    CryptoError,
    Side,
    crypto_draft,
    detect_exchange,
    parse_binance,
    parse_okx_orders,
)
from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import Instrument
from financial_app.domain.transactions import Origin, TransactionType

BINANCE_HEADER = "User ID,Time,Account,Operation,Coin,Change,Remark\n"
OKX_HEADER = (
    "UID:1,Account Type:Main\n"
    "Order ID,Order Time,Instrument,Symbol,Lvg,Side,Order Type,Order Amount,Filled Amount,Amount Unit,Order Price,"
    "Avg. Filled Price,Price Unit,PNL,Fee,Fee Unit,Status,Bot ID\n"
)


def binance(*rows: str) -> str:
    return BINANCE_HEADER + "\n".join(f"1,{row}" for row in rows) + "\n"


def okx(*rows: str) -> str:
    return OKX_HEADER + "\n".join(rows) + "\n"


def instrument(currency: str = "USD") -> Instrument:
    return Instrument(
        "Bitcoin", 1, currency, quantity_decimals=8, id=7, asset_class_name="Kryptowaluty", fallback_order=("yahoo",)
    )


def test_detects_the_exchange_by_header() -> None:
    assert detect_exchange(binance("2026-05-22 20:57:34,Spot,Transaction Buy,BTC,0.01,")) == BINANCE
    assert detect_exchange(okx()) == OKX
    assert detect_exchange("a,b,c\n") is None


def test_binance_fiat_purchase_and_convert() -> None:
    text = binance(
        "2024-01-05 21:53:52,Spot,Buy Crypto With Fiat,BTC,0.0113,Via CashBalance",
        "2025-06-16 09:32:30,Spot,Binance Convert,BTC,-0.0247,",
        "2024-02-29 08:18:05,Spot,Binance Convert,BTC,0.002,",
    )
    result = parse_binance(text)
    assert [(t.side, t.symbol, t.quantity, t.price) for t in result.trades] == [
        (Side.BUY, "BTC", Decimal("0.0113"), None),
        (Side.BUY, "BTC", Decimal("0.002"), None),
        (Side.SELL, "BTC", Decimal("0.0247"), None),
    ]
    assert result.trades[0].day == date(2024, 1, 5)
    assert not result.unsupported


def test_binance_spot_buy_is_net_of_its_fee() -> None:
    result = parse_binance(
        binance(
            "2026-05-22 20:57:34,Spot,Transaction Buy,BTC,0.01319,",
            "2026-05-22 20:57:34,Spot,Transaction Fee,BTC,-0.00001253,",
        )
    )
    (trade,) = result.trades
    assert trade.quantity == Decimal("0.01317747")


def test_binance_fee_before_buy_in_the_file_is_merged_too() -> None:
    result = parse_binance(
        binance(
            "2026-05-28 10:15:46,Spot,Transaction Fee,BTC,-0.00000389,",
            "2026-05-28 10:15:46,Spot,Transaction Buy,BTC,0.00409,",
        )
    )
    assert [t.quantity for t in result.trades] == [Decimal("0.00408611")]


def test_binance_transfers_between_wallets_are_ignored_and_withdrawals_unsupported() -> None:
    result = parse_binance(
        binance(
            "2026-06-13 13:01:09,Spot,Transfer Between Spot and Funding,BTC,-0.00000037,",
            "2026-06-13 13:01:09,Funding,Transfer Between Spot and Funding,BTC,0.00000037,",
            "2026-06-13 13:13:33,Spot,Transfer Funds to Spot,BTC,0.00000037,",
            "2026-06-13 13:20:47,Spot,Withdraw,BTC,-0.0465,Withdraw fee is included",
        )
    )
    assert result.trades == []
    assert [u.note for u in result.unsupported] == ["Withdraw: -0.0465 BTC"]


def test_binance_ids_are_stable_and_distinct() -> None:
    text = binance(
        "2024-02-29 08:18:05,Spot,Binance Convert,BTC,0.002,",
        "2024-02-29 08:18:05,Spot,Binance Convert,BTC,0.002,",
    )
    first = parse_binance(text).trades
    again = parse_binance(text).trades
    assert [t.external_id for t in first] == [t.external_id for t in again]
    assert len({t.external_id for t in first}) == 2
    assert all(t.external_id.startswith("binance-") for t in first)


def test_okx_buy_fee_in_base_reduces_quantity() -> None:
    text = okx(
        "1,2026-10-15 14:54:57,Spot,BTC-USDC,0.0,Buy,MARKET,300.0,0.0038,USDC,79805.6,79804.6,USDC,0,-0.00000752,BTC,"
        "COMPLETE,"
    )
    (trade,) = parse_okx_orders(text).trades
    assert (trade.side, trade.symbol, trade.quote) == (Side.BUY, "BTC", "USDC")
    assert trade.quantity == Decimal("0.00379248")
    # The whole price was paid for the quantity filled, so the price per unit received is higher
    assert trade.price is not None
    assert (trade.quantity * trade.price).quantize(Decimal("0.01")) == Decimal("303.26")
    assert trade.fee == 0
    assert trade.external_id == "okx-1"
    assert trade.day == date(2026, 10, 15)


def test_okx_sell_fee_in_quote_is_a_commission() -> None:
    text = okx(
        "2,2026-08-24 16:37:39,Spot,BTC-USDC,0.0,Sell,MARKET,0.0239,0.0239,USDC,79688.7,79685.13,USDC,0,-6.65,USDC,"
        "COMPLETE,"
    )
    (trade,) = parse_okx_orders(text).trades
    assert (trade.side, trade.quantity, trade.price, trade.fee) == (
        Side.SELL,
        Decimal("0.0239"),
        Decimal("79685.13"),
        Decimal("6.65"),
    )


def test_okx_unfinished_and_non_spot_orders_are_unsupported() -> None:
    text = okx(
        "3,2026-08-24 16:37:39,Spot,BTC-USDC,0.0,Buy,LIMIT,0.1,0.0,USDC,79688.7,0,USDC,0,0,BTC,CANCELED,",
        "4,2026-08-24 16:37:39,Swap,BTC-USDT-SWAP,3,Buy,MARKET,1,1,USDT,1,1,USDT,0,0,USDT,COMPLETE,",
    )
    result = parse_okx_orders(text)
    assert result.trades == []
    assert len(result.unsupported) == 2


NBP = NbpRate("USD", Decimal("4.0000"), date(2026, 10, 14), "1/A/NBP/2026")


def test_okx_draft_values_usdc_as_usd_at_the_nbp_rate() -> None:
    (trade,) = parse_okx_orders(
        okx("2,2026-08-24 16:37:39,Spot,BTC-USDC,0.0,Sell,MARKET,0.02,0.02,USDC,1000,1000,USDC,0,-0.5,USDC,COMPLETE,")
    ).trades
    draft = crypto_draft(trade, CryptoContext(3, instrument(), NBP))
    assert draft.transaction_type is TransactionType.SELL
    assert draft.origin is Origin.BROKER
    assert draft.external_id == "okx-2"
    assert draft.quantity == Decimal("0.02")
    assert draft.commission == Decimal("2.00")
    # 0.02 x 1000 USD x 4.0 = 80.00 PLN, less the 2.00 PLN fee
    assert draft.actual_amount == Decimal("78.00")


def test_binance_draft_needs_a_market_price() -> None:
    (trade,) = parse_binance(binance("2024-01-05 21:53:52,Spot,Buy Crypto With Fiat,BTC,0.01,")).trades
    with pytest.raises(CryptoError, match="cen"):
        crypto_draft(trade, CryptoContext(3, instrument(), NBP))
    draft = crypto_draft(trade, CryptoContext(3, instrument(), NBP, market_price=Decimal("40000")))
    assert draft.transaction_type is TransactionType.BUY
    assert draft.actual_amount == Decimal("1600.00")  # 0.01 x 40000 USD x 4.0


def test_a_usdc_trade_needs_a_usd_instrument() -> None:
    (trade,) = parse_okx_orders(
        okx("2,2026-08-24 16:37:39,Spot,BTC-USDC,0.0,Sell,MARKET,0.02,0.02,USDC,1000,1000,USDC,0,0,USDC,COMPLETE,")
    ).trades
    with pytest.raises(CryptoError, match="USD"):
        crypto_draft(trade, CryptoContext(3, instrument("PLN"), None))
