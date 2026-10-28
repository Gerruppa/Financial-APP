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
    parse_exchange,
    parse_okx_orders,
    transfer_draft,
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


def test_binance_wallet_moves_are_ignored() -> None:
    result = parse_binance(
        binance(
            "2026-06-13 13:01:09,Spot,Transfer Between Spot and Funding,BTC,-0.00000037,",
            "2026-06-13 13:01:09,Funding,Transfer Between Spot and Funding,BTC,0.00000037,",
            "2026-06-13 13:13:33,Spot,Transfer Funds to Spot,BTC,0.00000037,",
        )
    )
    assert (result.trades, result.transfers, result.unsupported) == ([], [], [])


def test_binance_withdrawal_is_a_transfer_and_its_network_fee_a_sale_for_commission() -> None:
    result = parse_binance(
        binance(
            "2026-06-13 13:20:47,Spot,Withdraw,BTC,-0.0465,Withdraw fee is included",
            "2026-06-13 13:20:47,Spot,Withdraw,BTC,-0.00012,Withdraw fee is included",
            "2026-07-01 08:00:00,Spot,Withdraw,BTC,-0.01,Withdraw fee is included",
        )
    )
    assert [(t.day, t.symbol, t.quantity) for t in result.transfers] == [
        (date(2026, 6, 13), "BTC", Decimal("0.0465")),
        (date(2026, 7, 1), "BTC", Decimal("0.01")),
    ]
    assert len({t.external_id for t in result.transfers}) == 2
    assert all(t.external_id.startswith("binance-") for t in result.transfers)
    assert result.unsupported == []
    # The network fee is coins gone from the exchange's Account: a sale whose whole value is the commission
    (fee,) = result.trades
    assert (fee.day, fee.side, fee.symbol, fee.quantity, fee.price) == (
        date(2026, 6, 13),
        Side.SELL,
        "BTC",
        Decimal("0.00012"),
        None,
    )
    assert fee.fee_is_value and fee.external_id.startswith("binance-") and "-fee-" in fee.external_id


def test_a_network_fee_draft_sells_the_coins_for_a_commission_of_their_whole_value() -> None:
    (fee,) = parse_binance(
        binance(
            "2026-06-13 13:20:47,Spot,Withdraw,BTC,-0.0465,",
            "2026-06-13 13:20:47,Spot,Withdraw,BTC,-0.00012,",
        )
    ).trades
    draft = crypto_draft(fee, CryptoContext(3, instrument(), NBP, market_price=Decimal("50000")))
    assert (draft.transaction_type, draft.quantity) == (TransactionType.SELL, Decimal("0.00012"))
    # 0.00012 BTC x 50000 USD x 4.0 = 24 PLN, all of it commission but a grosz (a Sell must bring something)
    assert draft.commission == Decimal("23.99")
    assert draft.actual_amount == Decimal("0.01")


def test_a_transfer_becomes_a_security_transfer_to_the_wallet() -> None:
    (transfer,) = parse_binance(binance("2026-06-13 13:20:47,Spot,Withdraw,BTC,-0.0465,")).transfers
    draft = transfer_draft(transfer, 3, 4, instrument())
    assert draft.transaction_type is TransactionType.SECURITY_TRANSFER
    assert (draft.account_id, draft.target_account_id, draft.quantity) == (3, 4, Decimal("0.0465"))
    assert (draft.instrument_id, draft.origin, draft.external_id) == (7, Origin.BROKER, transfer.external_id)


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


OKX_FILLS_HEADER = (
    "UID:1,Account Type:Main\n"
    "Order ID,Trade ID,Trade Time,Instrument,Symbol,Filled Amount,Filled Amount Unit,Filled Price,Fill Price Unit,"
    "Trading Volume,Trading Volume Unit,taker/maker,Fee,Fee Unit\n"
)


def okx_fills(*rows: str) -> str:
    return OKX_FILLS_HEADER + "\n".join(rows) + "\n"


def test_okx_trade_details_are_detected_as_okx() -> None:
    assert detect_exchange(okx_fills()) == OKX


def test_okx_sell_quantity_comes_from_the_fills_not_the_rounded_order() -> None:
    # The order says 0.0239 BTC, rounded to 4 places; its two fills are worth 0.02125 + 0.0026 BTC
    orders = okx(
        "2,2026-08-24 16:37:39,Spot,BTC-USDC,0.0,Sell,MARKET,0.0239,0.0239,USDC,79688.7,79685.13,USDC,0,-6.65,USDC,"
        "COMPLETE,"
    )
    fills = okx_fills(
        "2,11,2026-08-24 16:37:39,Spot,BTC-USDC,0.0213,BTC,100,USDC,2125,BTC,taker,0,USDC",
        "2,12,2026-08-24 16:37:39,Spot,BTC-USDC,0.0026,BTC,200,USDC,520,BTC,taker,0,USDC",
    )
    result = parse_exchange(OKX, [orders, fills])
    (trade,) = result.trades
    assert trade.quantity == Decimal("23.85")
    assert result.unsupported == []


def test_okx_buy_quantity_from_fills_is_rounded_to_eight_places_before_the_fee() -> None:
    orders = okx(
        "1,2026-10-15 14:54:57,Spot,BTC-USDC,0.0,Buy,MARKET,300.0,0.0038,USDC,79805.6,79804.6,USDC,0,-0.00000752,BTC,"
        "COMPLETE,"
    )
    fills = okx_fills("1,5,2026-10-15 14:54:57,Spot,BTC-USDC,0.0038,BTC,79804.6,USDC,299.99985623,USDC,taker,-1,BTC")
    (trade,) = parse_exchange(OKX, [orders, fills]).trades
    # 299.99985623 / 79804.6 = 0.00375918000002..., less the fee of 0.00000752
    assert trade.quantity == Decimal("0.00375166")


def test_okx_order_without_fills_keeps_the_rounded_quantity_and_says_so() -> None:
    orders = okx(
        "2,2026-08-24 16:37:39,Spot,BTC-USDC,0.0,Sell,MARKET,0.0239,0.0239,USDC,79688.7,79685.13,USDC,0,-6.65,USDC,"
        "COMPLETE,"
    )
    result = parse_exchange(OKX, [orders])
    assert [t.quantity for t in result.trades] == [Decimal("0.0239")]
    assert len(result.unsupported) == 1
    assert "Trade Details" in result.unsupported[0].note


OKX_FUNDING_HEADER = (
    "UID:1,Account Type:Main,Time Zone:UTC+8\nid,Time,Type,Amount,Before Balance,After Balance,Symbol,Amount-USD\n"
)


def okx_funding(*rows: str) -> str:
    return OKX_FUNDING_HEADER + "\n".join(rows) + "\n"


FUNDING = okx_funding(
    "10,2026-10-25 02:57:27,Buy,0.001555455453100900,0E-18,0.0015554554531,BTC,125.03166145",
    "11,2026-10-25 02:57:27,To unified trading account,-0.00155545,0.0015554554531,5.4E-9,BTC,-125.03",
    "12,2026-08-24 23:36:20,Deposit,0.023851040000000000,0E-18,0.02385104,BTC,1885.24641288",
    "13,2026-08-24 23:36:20,To unified trading account,-0.02385104,0.02385104,0E-18,BTC,-1885.24",
    "14,2026-07-06 01:33:31,Deposit,1994.721006,0E-18,1994.721006,USDC,1994.12113555",
    "15,2026-07-05 13:54:36,From unified trading account,0.00916493,2.2E-10,0.0091649302,BNB,5.23558029",
    "16,2026-07-05 13:54:45,Withdrawal,-0.009164930000000000,0.0091649302,2.2E-10,BNB,-5.23558029",
)


def test_okx_funding_history_is_detected_as_okx() -> None:
    assert detect_exchange(FUNDING) == OKX


def test_okx_funding_buy_is_a_trade_priced_from_its_usd_value_in_utc() -> None:
    (trade,) = parse_exchange(OKX, [FUNDING]).trades
    # 02:57 on 25 October in UTC+8 is the evening of 24 October in UTC
    assert (trade.day, trade.side, trade.symbol, trade.quote, trade.external_id) == (
        date(2026, 10, 24),
        Side.BUY,
        "BTC",
        "USD",
        "okx-funding-10",
    )
    # Rounded down, so it never exceeds what the exchange moved on
    assert trade.quantity == Decimal("0.00155545")
    assert trade.price is not None
    assert (trade.quantity * trade.price).quantize(Decimal("0.01")) == Decimal("125.03")


def test_okx_funding_deposit_and_withdrawal_are_transfers_and_stablecoins_and_moves_are_left_out() -> None:
    result = parse_exchange(OKX, [FUNDING])
    assert [(t.external_id, t.day, t.symbol, t.quantity, t.incoming) for t in result.transfers] == [
        ("okx-funding-16", date(2026, 7, 5), "BNB", Decimal("0.00916493"), False),
        ("okx-funding-12", date(2026, 8, 24), "BTC", Decimal("0.02385104"), True),
    ]
    assert result.unsupported == []


def test_an_incoming_transfer_goes_from_the_wallet_to_the_exchange_account() -> None:
    (transfer, *_) = [t for t in parse_exchange(OKX, [FUNDING]).transfers if t.incoming]
    draft = transfer_draft(transfer, 3, 4, instrument())
    assert (draft.account_id, draft.target_account_id, draft.quantity) == (4, 3, Decimal("0.02385104"))
    assert draft.external_id == "okx-funding-12"


def test_okx_funding_row_of_an_unknown_type_is_unsupported() -> None:
    result = parse_exchange(OKX, [okx_funding("20,2026-07-05 13:54:36,Rebate,0.5,0,0.5,BTC,40")])
    assert len(result.unsupported) == 1
    assert "Rebate" in result.unsupported[0].note


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
