"""Importing Binance and OKX CSV exports as Transactions (spec 7).

Nothing is saved until the user has seen the preview and applied it: ``preview_crypto`` only reads, ``apply_crypto``
saves every new trade or none. The exchange's Account and each coin's Instrument are remembered in the app settings.
Trades imported before (by their external id) are not offered again, so overlapping exports can be imported again.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine

from financial_app.domain.crypto_import import (
    CryptoContext,
    CryptoError,
    CryptoRead,
    CryptoTrade,
    Unsupported,
    crypto_draft,
    detect_exchange,
    parse_exchange,
)
from financial_app.domain.currencies import MissingNbpRateError, NbpRate
from financial_app.domain.formatting import format_date
from financial_app.domain.instruments import Instrument
from financial_app.domain.prices import YAHOO, PriceSourceError
from financial_app.domain.transactions import PLN, TransactionDraft, TransactionError
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.reconciliation import AddBroker, apply_reconciliation, handled_broker_ids
from financial_app.persistence.settings import CRYPTO_ACCOUNT, CRYPTO_COIN, load_setting, save_setting
from financial_app.sources.spreadsheet import NbpLookup
from financial_app.sources.yahoo import YahooSource

# How far back a market price is looked for when the day itself has no close
PRICE_WINDOW_DAYS = 7

# A coin's market price in an Instrument's currency on a day: (Yahoo symbol, currency, day) -> price
PriceLookup = Callable[[str, str, date], Decimal]


@dataclass(frozen=True)
class CryptoFile:
    """The trades of one exchange's export (a file, or the files of a folder) and what could not be read."""

    exchange: str
    trades: list[CryptoTrade]
    unsupported: list[Unsupported]


@dataclass(frozen=True)
class CryptoDecisions:
    """The user's choices: the Account the trades go into (None: not chosen) and an Instrument per coin symbol."""

    account_id: int | None = None
    instruments: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Problem:
    trade: CryptoTrade
    message: str


@dataclass(frozen=True)
class CryptoPreview:
    file: CryptoFile
    account_id: int | None
    # Coins with no Instrument yet
    unmatched_coins: list[str]
    drafts: list[TransactionDraft]
    problems: list[Problem]
    # Trades imported before
    handled: int

    @property
    def blocked(self) -> bool:
        return self.account_id is None or bool(self.unmatched_coins or self.problems)


def read_crypto(path: Path) -> CryptoFile:
    """The trades in a Binance or OKX CSV file, or in the CSV files of a folder (one exchange only); raises
    CryptoError if nothing can be read."""
    files = sorted(path.glob("*.csv")) if path.is_dir() else [path]
    if not files:
        raise CryptoError(f"W folderze {path.name} nie ma plików .csv.")
    found: dict[str, list[str]] = {}
    for file in files:
        try:
            text = file.read_text(encoding="utf-8-sig")
        except OSError, UnicodeDecodeError:
            raise CryptoError(f"Nie udało się otworzyć pliku {file.name}.") from None
        exchange = detect_exchange(text)
        if exchange is not None:
            found.setdefault(exchange, []).append(text)
        elif not path.is_dir():
            raise CryptoError(f"Plik {file.name} nie wygląda na eksport z Binance ani OKX (CSV).")
    if not found:
        raise CryptoError(f"W folderze {path.name} nie ma plików z Binance ani OKX.")
    if len(found) > 1:
        raise CryptoError("Wskaż pliki jednej giełdy naraz.")
    ((exchange, texts),) = found.items()
    read: CryptoRead = parse_exchange(exchange, texts)
    return CryptoFile(exchange, read.trades, read.unsupported)


def yahoo_prices(source: YahooSource) -> PriceLookup:
    """A ``PriceLookup`` on Yahoo's daily closes: the day's, else the last one in the days before it."""

    # The preview is redrawn on every choice, so a price already fetched is kept
    known: dict[tuple[str, str, date], Decimal] = {}

    def price(symbol: str, currency: str, day: date) -> Decimal:
        key = (symbol, currency, day)
        if key not in known:
            quotes = source.history(symbol, currency, day - timedelta(days=PRICE_WINDOW_DAYS), day)
            if not quotes:
                raise CryptoError(f"Yahoo nie podaje ceny {symbol} z {format_date(day)}.")
            known[key] = quotes[-1].price
        return known[key]

    return price


def match_coin(symbol: str, instruments: Mapping[int, Instrument]) -> Instrument | None:
    """The one Instrument a coin symbol names: by its Yahoo symbol ("BTC-USD", "BTC-PLN") or its name being the
    symbol; None when none or several do."""
    found = [
        instrument
        for instrument in instruments.values()
        if instrument.source_symbols.get(YAHOO, "").upper().partition("-")[0] == symbol.upper()
        or instrument.name.casefold() == symbol.casefold()
    ]
    return found[0] if len(found) == 1 else None


def _account(engine: Engine, exchange: str, decisions: CryptoDecisions) -> int | None:
    if decisions.account_id is not None:
        return decisions.account_id
    saved = load_setting(engine, CRYPTO_ACCOUNT + exchange)
    return int(saved) if saved is not None else None


def _instrument(
    engine: Engine, symbol: str, instruments: Mapping[int, Instrument], decisions: CryptoDecisions
) -> Instrument | None:
    chosen = decisions.instruments.get(symbol)
    if chosen is None and (saved := load_setting(engine, CRYPTO_COIN + symbol)) is not None:
        chosen = int(saved)
    if chosen is not None and chosen in instruments:
        return instruments[chosen]
    return match_coin(symbol, instruments)


def preview_crypto(
    engine: Engine, file: CryptoFile, rates: NbpLookup, prices: PriceLookup, decisions: CryptoDecisions
) -> CryptoPreview:
    """Match the account and coins and turn the trades not imported before into Transactions, without saving."""
    instruments = {instrument.id: instrument for instrument in list_instruments(engine)}
    account_id = _account(engine, file.exchange, decisions)
    handled = handled_broker_ids(engine)
    trades = [trade for trade in file.trades if trade.external_id not in handled]
    resolved = {trade.symbol: _instrument(engine, trade.symbol, instruments, decisions) for trade in trades}
    unmatched = [symbol for symbol, found in resolved.items() if found is None]

    drafts: list[TransactionDraft] = []
    problems: list[Problem] = []
    if account_id is not None:
        for trade in trades:
            instrument = resolved[trade.symbol]
            if instrument is None:
                continue
            try:
                drafts.append(crypto_draft(trade, _context(trade, account_id, instrument, rates, prices)))
            except (TransactionError, PriceSourceError, MissingNbpRateError) as error:
                problems.append(Problem(trade, str(error)))
    return CryptoPreview(file, account_id, unmatched, drafts, problems, len(file.trades) - len(trades))


def _context(
    trade: CryptoTrade, account_id: int, instrument: Instrument, rates: NbpLookup, prices: PriceLookup
) -> CryptoContext:
    currency = instrument.quote_currency
    nbp_rate: NbpRate | None = None if currency == PLN else rates.before(currency, trade.day)
    market_price = None
    if trade.price is None:
        symbol = instrument.source_symbols.get(YAHOO)
        if symbol is None:
            raise CryptoError(f"Instrument „{instrument.name}” nie ma symbolu Yahoo, by pobrać cenę {trade.symbol}.")
        market_price = prices(symbol, currency, trade.day)
    return CryptoContext(account_id, instrument, nbp_rate, market_price)


def apply_crypto(
    engine: Engine,
    file: CryptoFile,
    rates: NbpLookup,
    prices: PriceLookup,
    decisions: CryptoDecisions,
    today: date,
) -> CryptoPreview:
    """Save every new trade, all or none, and remember the matches; returns what was applied.

    Raises CryptoError if the Account or a coin is unmatched or a trade cannot become a Transaction; nothing is saved
    then.
    """
    preview = preview_crypto(engine, file, rates, prices, decisions)
    if preview.account_id is None or preview.unmatched_coins:
        raise CryptoError("Wybierz konto i instrument dla każdej monety.")
    if preview.problems:
        first = preview.problems[0]
        raise CryptoError(f"Transakcja z {format_date(first.trade.day)}: {first.message}")
    apply_reconciliation(engine, [AddBroker(draft) for draft in preview.drafts], today)
    save_setting(engine, CRYPTO_ACCOUNT + file.exchange, str(preview.account_id))
    for symbol, instrument_id in decisions.instruments.items():
        save_setting(engine, CRYPTO_COIN + symbol, str(instrument_id))
    return preview
