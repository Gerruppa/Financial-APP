"""Reading a crypto exchange's CSV export (Binance, OKX) into Transactions (spec 7).

Pure: ``sources/crypto.py`` reads the files and hands over their text.

- Binance's "Transaction History" is a ledger of coin movements without prices: a "Buy Crypto With Fiat", a "Binance
  Convert" (positive: bought, negative: sold) and a "Transaction Buy" with its "Transaction Fee" (taken from the coin
  bought, so the quantity is net of it) are trades; the price comes from the market on that day. Moves between the
  Spot and Funding wallets are ignored, anything else (a withdrawal, ...) is listed as not supported.
- OKX's "Order History" has one row per order with its average price in the quote coin (USDC, valued as USD). A
  Buy's fee is in the coin bought, so the quantity is net of it and the price per unit received is higher; a Sell's
  fee is in the quote coin, a commission. Only completed Spot orders count.
- OKX's "Funding History" (Wallet Bill History) holds what the orders lack: a "Buy" outside Spot (valued by its
  Amount-USD) and the coins deposited from or withdrawn to the user's own wallet, which become transfers; cash in
  stablecoins and the moves to and from the trading account are ignored. Its times are in the zone named on its
  first line (UTC+8), the Order History's are taken as UTC (a deposit then comes just before the sale it funds).
"""

import csv
import io
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from enum import StrEnum
from types import MappingProxyType

from financial_app.domain.currencies import NbpRate
from financial_app.domain.formatting import format_date
from financial_app.domain.instruments import Instrument
from financial_app.domain.transactions import (
    GROSZ,
    PLN,
    Origin,
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    security_transfer,
)

BINANCE = "binance"
OKX = "okx"
EXCHANGE_NAMES = {BINANCE: "Binance", OKX: "OKX"}
# Stablecoins that count as the US dollar
USD_COINS = ("USD", "USDC", "USDT")
USD = "USD"
UNIT = Decimal("0.00000001")

BINANCE_COLUMNS = ("User ID", "Time", "Account", "Operation", "Coin", "Change", "Remark")
OKX_COLUMNS = ("Order ID", "Order Time", "Instrument", "Symbol", "Side", "Avg. Filled Price", "Fee Unit", "Status")
OKX_FILL_COLUMNS = ("Order ID", "Trade ID", "Filled Price", "Trading Volume")
OKX_FUNDING_COLUMNS = ("id", "Time", "Type", "Amount", "Symbol", "Amount-USD")
# The funding ledger's moves between the funding and trading accounts change nothing in the portfolio
OKX_FUNDING_IGNORED = ("To unified trading account", "From unified trading account")
TRADE_OPERATIONS = ("Buy Crypto With Fiat", "Binance Convert")
IGNORED_OPERATIONS = ("Transfer Between Spot and Funding", "Transfer Funds to Spot", "Transfer Funds to Funding Wallet")


class CryptoError(TransactionError):
    """A crypto export that cannot be read or become a Transaction; the message is Polish, for the user."""


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class CryptoTrade:
    """One buy or sell of ``quantity`` units of coin ``symbol`` (net of a fee taken from it) on ``day``.

    ``price`` is per unit in the ``quote`` coin, None when the export gives none (Binance); ``fee`` is a commission in
    the quote coin. ``fee_is_value``: the whole value of the units (a network fee paid in the coin) is the commission,
    so the sale moves no cash."""

    exchange: str
    external_id: str
    day: date
    side: Side
    symbol: str
    quantity: Decimal
    price: Decimal | None = None
    quote: str = ""
    fee: Decimal = Decimal(0)
    fee_is_value: bool = False


@dataclass(frozen=True)
class CryptoTransfer:
    """``quantity`` units of coin ``symbol`` withdrawn from the exchange to the user's own wallet on ``day``, or, when
    ``incoming``, deposited from the wallet to the exchange."""

    exchange: str
    external_id: str
    day: date
    symbol: str
    quantity: Decimal
    incoming: bool = False


@dataclass(frozen=True)
class Unsupported:
    day: date
    note: str


@dataclass(frozen=True)
class CryptoRead:
    trades: list[CryptoTrade]
    unsupported: list[Unsupported]
    transfers: list[CryptoTransfer] = field(default_factory=list)


def detect_exchange(text: str) -> str | None:
    """Which exchange's export the text is, by its header; None for anything else."""
    for exchange, columns, skip in (
        (BINANCE, BINANCE_COLUMNS, 0),
        (OKX, OKX_COLUMNS, 1),
        (OKX, OKX_FILL_COLUMNS, 1),
        (OKX, OKX_FUNDING_COLUMNS, 1),
    ):
        if _has_columns(text, columns, skip):
            return exchange
    return None


def _has_columns(text: str, columns: tuple[str, ...], skip: int) -> bool:
    lines = text.lstrip("﻿").splitlines()
    if len(lines) <= skip:
        return False
    header = next(csv.reader([lines[skip]]), [])
    return all(column in header for column in columns)


def _rows(text: str, skip: int) -> list[dict[str, str]]:
    lines = text.lstrip("﻿").splitlines()[skip:]
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


def _day(moment: str) -> date:
    try:
        return datetime.strptime(moment.strip(), "%Y-%m-%d %H:%M:%S").date()
    except ValueError:
        raise CryptoError(f"Nieprawidłowa data „{moment}” w pliku giełdy.") from None


def _number(value: str, what: str) -> Decimal:
    try:
        return Decimal(value.strip())
    except ArithmeticError:
        raise CryptoError(f"Nieprawidłowa liczba „{value}” ({what}) w pliku giełdy.") from None


def parse_binance(text: str) -> CryptoRead:
    """The trades of a Binance "Transaction History" CSV and the rows it cannot import."""
    trades: list[CryptoTrade] = []
    unsupported: list[Unsupported] = []
    # A spot trade is a "Transaction Buy" and a "Transaction Fee" at the same second, in either order
    spot: dict[tuple[str, str], dict[str, Decimal]] = {}
    # A withdrawal is one row, or two at the same second: the transfer and the network fee, the smaller one
    withdrawals: dict[tuple[str, str], list[Decimal]] = {}
    seen: dict[str, int] = {}

    def identify(base: str) -> str:
        seen[base] = seen.get(base, 0) + 1
        return f"binance-{base}-{seen[base]}"

    for row in _rows(text, 0):
        moment, operation, coin = row["Time"].strip(), row["Operation"].strip(), row["Coin"].strip()
        change = _number(row["Change"], "Change")
        if operation in IGNORED_OPERATIONS:
            continue
        if operation == "Withdraw":
            withdrawals.setdefault((moment, coin), []).append(abs(change))
        elif operation in ("Transaction Buy", "Transaction Fee"):
            spot.setdefault((moment, coin), {})[operation] = change
        elif operation in TRADE_OPERATIONS and change != 0:
            side = Side.BUY if change > 0 else Side.SELL
            key = identify(f"{moment}-{operation}-{coin}")
            trades.append(CryptoTrade(BINANCE, key, _day(moment), side, coin, abs(change)))
        else:
            unsupported.append(Unsupported(_day(moment), f"{operation}: {change} {coin}"))
    for (moment, coin), parts in spot.items():
        bought = parts.get("Transaction Buy")
        if bought is None:
            unsupported.append(Unsupported(_day(moment), f"Transaction Fee: {parts['Transaction Fee']} {coin}"))
            continue
        net = bought + parts.get("Transaction Fee", Decimal(0))
        trades.append(CryptoTrade(BINANCE, identify(f"{moment}-spot-{coin}"), _day(moment), Side.BUY, coin, net))
    transfers: list[CryptoTransfer] = []
    for (moment, coin), amounts in withdrawals.items():
        moved, *fees = sorted(amounts, reverse=True)
        transfers.append(CryptoTransfer(BINANCE, identify(f"{moment}-withdraw-{coin}"), _day(moment), coin, moved))
        for fee in fees:
            key = identify(f"{moment}-fee-{coin}")
            trades.append(CryptoTrade(BINANCE, key, _day(moment), Side.SELL, coin, fee, fee_is_value=True))
    return CryptoRead(sorted(trades, key=lambda t: t.day), unsupported, sorted(transfers, key=lambda t: t.day))


def _funding_utc(text: str, moment: str) -> date:
    """The UTC day of a Funding History time, in the zone its first line names (``Time Zone:UTC+8``)."""
    zone = re.search(r"Time Zone:UTC([+-]\d+)", text.lstrip("﻿").partition("\n")[0])
    offset = timedelta(hours=int(zone.group(1))) if zone else timedelta(0)
    try:
        return (datetime.strptime(moment.strip(), "%Y-%m-%d %H:%M:%S") - offset).date()
    except ValueError:
        raise CryptoError(f"Nieprawidłowa data „{moment}” w pliku giełdy.") from None


def parse_okx_funding(text: str) -> CryptoRead:
    """The trades and transfers of an OKX "Funding History" CSV and the rows it cannot import. Quantities are rounded
    down to 8 places, so a transfer never exceeds what was bought; the price of a Buy is its USD value per unit."""
    trades: list[CryptoTrade] = []
    transfers: list[CryptoTransfer] = []
    unsupported: list[Unsupported] = []
    for row in _rows(text, 1):
        kind, symbol = row["Type"].strip(), row["Symbol"].strip()
        if kind in OKX_FUNDING_IGNORED or (symbol in USD_COINS and kind in ("Deposit", "Withdrawal")):
            continue
        day = _funding_utc(text, row["Time"])
        amount = _number(row["Amount"], "Amount")
        key = f"okx-funding-{row['id'].strip()}"
        quantity = abs(amount).quantize(UNIT, rounding=ROUND_DOWN)
        if kind == "Buy" and amount > 0:
            price = (_number(row["Amount-USD"], "Amount-USD") / amount).quantize(UNIT)
            trades.append(CryptoTrade(OKX, key, day, Side.BUY, symbol, quantity, price, USD))
        elif kind in ("Deposit", "Withdrawal"):
            transfers.append(CryptoTransfer(OKX, key, day, symbol, quantity, incoming=kind == "Deposit"))
        else:
            unsupported.append(Unsupported(day, f"{kind}: {amount} {symbol}"))
    return CryptoRead(sorted(trades, key=lambda t: t.day), unsupported, sorted(transfers, key=lambda t: t.day))


def parse_okx_fills(text: str) -> dict[str, Decimal]:
    """The exact quantity of each order in an OKX "Trade Details" CSV: the Order History rounds its Filled Amount to 4
    places, so the quantity is each fill's Trading Volume over its Filled Price, summed over the fills and rounded to 8
    places (the finest unit a coin is held in)."""
    quantities: dict[str, Decimal] = {}
    for row in _rows(text, 1):
        price = _number(row["Filled Price"], "Filled Price")
        if price == 0:
            continue
        order = row["Order ID"].strip()
        quantities[order] = quantities.get(order, Decimal(0)) + _number(row["Trading Volume"], "Trading Volume") / price
    return {order: quantity.quantize(UNIT) for order, quantity in quantities.items()}


def parse_okx_orders(text: str, fills: Mapping[str, Decimal] = MappingProxyType({})) -> CryptoRead:
    """The trades of an OKX "Order History" CSV (its first line names the account) and the orders it cannot import.
    ``fills`` are the exact quantities by order id (``parse_okx_fills``); an order without one keeps the rounded Filled
    Amount, which is listed as a warning."""
    trades: list[CryptoTrade] = []
    unsupported: list[Unsupported] = []
    for row in _rows(text, 1):
        day = _day(row["Order Time"])
        symbol = row["Symbol"].strip()
        base, _, quote = symbol.partition("-")
        label = f"{row['Instrument'].strip()} {symbol} {row['Side'].strip()}"
        filled = _number(row["Filled Amount"] or "0", "Filled Amount")
        if row["Instrument"].strip() != "Spot" or not quote or row["Side"].strip() not in ("Buy", "Sell"):
            unsupported.append(Unsupported(day, f"Zlecenie {label}: tylko Spot Buy/Sell."))
            continue
        if row["Status"].strip() != "COMPLETE" or filled == 0:
            unsupported.append(
                Unsupported(day, f"Zlecenie {label} ({row['Status'].strip()}) nie zostało zrealizowane.")
            )
            continue
        order_id = row["Order ID"].strip()
        if order_id in fills:
            filled = fills[order_id]
        else:
            unsupported.append(
                Unsupported(day, f"Zlecenie {label}: brak w Trade Details, ilość jest zaokrąglona do 4 miejsc.")
            )
        price = _number(row["Avg. Filled Price"], "Avg. Filled Price")
        fee = abs(_number(row["Fee"] or "0", "Fee"))
        fee_unit = row["Fee Unit"].strip()
        if row["Side"].strip() == "Buy":
            quantity, unit_price, commission = _buy(filled, price, fee, fee_unit, base)
            side = Side.BUY
        else:
            quantity, unit_price, commission = filled, price, _quote_fee(fee, fee_unit, quote)
            side = Side.SELL
        if quantity is None or commission is None:
            unsupported.append(Unsupported(day, f"Zlecenie {label}: prowizja w {fee_unit}."))
            continue
        key = f"okx-{row['Order ID'].strip()}"
        trades.append(CryptoTrade(OKX, key, day, side, base, quantity, unit_price, quote, commission))
    return CryptoRead(sorted(trades, key=lambda t: t.day), unsupported)


def _buy(
    filled: Decimal, price: Decimal, fee: Decimal, fee_unit: str, base: str
) -> tuple[Decimal | None, Decimal, Decimal | None]:
    """Quantity received, price per unit received and commission of an OKX Buy: a fee in the coin bought is taken out
    of the quantity (the price paid stays), a fee in another coin is a commission."""
    if fee_unit != base:
        return filled, price, None if fee else Decimal(0)
    net = (filled - fee).quantize(UNIT)
    return net, (filled * price / net).quantize(UNIT), Decimal(0)


def _quote_fee(fee: Decimal, fee_unit: str, quote: str) -> Decimal | None:
    return fee if fee_unit == quote or not fee else None


@dataclass(frozen=True)
class CryptoContext:
    """What a trade needs to become a Transaction: its Account, Instrument, the NBP Rate of the Instrument's currency
    on its day (None for PLN) and, when the export gives no price, the market price of the day in that currency."""

    account_id: int
    instrument: Instrument
    nbp_rate: NbpRate | None
    market_price: Decimal | None = None


def crypto_draft(trade: CryptoTrade, context: CryptoContext) -> TransactionDraft:
    """The Transaction a trade becomes, with Origin "import od brokera" and the trade's external id. A USD, USDC or
    USDT price is valued at the NBP USD rate; the commission is in PLN."""
    instrument = context.instrument
    currency = instrument.quote_currency
    if trade.price is not None and trade.quote in USD_COINS and currency != USD:
        raise CryptoError(f"Zlecenie z {format_date(trade.day)} jest w {trade.quote}: instrument musi być w USD.")
    price = trade.price if trade.price is not None else context.market_price
    if price is None:
        raise CryptoError(f"Brak ceny {trade.symbol} z {format_date(trade.day)}: nie udało się jej pobrać.")
    rate = Decimal(1)
    if currency != PLN:
        if context.nbp_rate is None:
            raise CryptoError(f"Brak kursu NBP {currency} dla {format_date(trade.day)}.")
        rate = context.nbp_rate.rate
    if trade.fee_is_value:
        # A Sell must bring something, so the commission is the value less a grosz
        commission = (trade.quantity * price * rate).quantize(GROSZ, rounding=ROUND_HALF_UP) - GROSZ
    else:
        commission = (trade.fee * rate).quantize(GROSZ)
    side = TransactionType.BUY if trade.side is Side.BUY else TransactionType.SELL
    draft = buy_or_sell(
        context.account_id,
        trade.day,
        side,
        instrument.id,
        trade.quantity,
        price,
        commission,
        EXCHANGE_NAMES[trade.exchange],
        nbp_rate=context.nbp_rate,
    )
    return replace(draft, origin=Origin.BROKER, external_id=trade.external_id)


def transfer_draft(
    transfer: CryptoTransfer, account_id: int, target_account_id: int, instrument: Instrument
) -> TransactionDraft:
    """The Security Transfer of a withdrawal to the wallet's Account (a deposit: from it), with Origin "import od
    brokera" and its id. ``account_id`` is the exchange's Account, ``target_account_id`` the wallet's."""
    source, target = (target_account_id, account_id) if transfer.incoming else (account_id, target_account_id)
    draft = security_transfer(
        source, transfer.day, target, instrument.id, transfer.quantity, EXCHANGE_NAMES[transfer.exchange]
    )
    return replace(draft, origin=Origin.BROKER, external_id=transfer.external_id)


def parse_exchange(exchange: str, texts: Iterable[str]) -> CryptoRead:
    """Merge the reads of several files of one exchange."""
    if exchange == BINANCE:
        reads = [parse_binance(text) for text in texts]
    else:
        # OKX's "Trade Details" only give the exact quantities of the orders in its "Order History"
        files = list(texts)
        details = [text for text in files if _has_columns(text, OKX_FILL_COLUMNS, 1)]
        funding = [text for text in files if _has_columns(text, OKX_FUNDING_COLUMNS, 1)]
        fills = {order: quantity for text in details for order, quantity in parse_okx_fills(text).items()}
        orders = [text for text in files if text not in details and text not in funding]
        reads = [parse_okx_orders(text, fills) for text in orders] + [parse_okx_funding(text) for text in funding]
    return CryptoRead(
        [t for r in reads for t in r.trades],
        [u for r in reads for u in r.unsupported],
        [t for r in reads for t in r.transfers],
    )
