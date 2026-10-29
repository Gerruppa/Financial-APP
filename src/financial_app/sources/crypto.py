"""Importing Binance, OKX and Trezor CSV exports as Transactions (spec 7).

A file, or a folder with the exports of any of them (subfolders too), is read into one ``CryptoFile`` per source,
the exchanges first. Nothing is saved until the user has seen the preview and applied it: ``preview_crypto`` only
reads, ``apply_crypto`` saves every new trade of every source or none. Each source's Account and wallet and each
coin's Instrument are remembered in the app settings. Trades imported before (by their external id) are not offered
again, so overlapping exports can be imported again; a row in two files of the folder counts once.

A transfer between an exchange and the wallet is in both exports: whichever is read second pairs with the first's
Security Transfer, saved before or added by the same import, and adds nothing. A Trezor is a wallet: its Account is the
wallet's; the user chooses the other Account of each transfer that pairs with none, skips it, or leaves it for later,
when the exchange's export that explains it may have been read.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine

from financial_app.domain.crypto_import import (
    EXCHANGE_NAMES,
    TREZOR,
    CryptoContext,
    CryptoError,
    CryptoRead,
    CryptoTrade,
    CryptoTransfer,
    Unsupported,
    crypto_draft,
    detect_exchange,
    pair_transfers,
    parse_exchange,
    transfer_draft,
)
from financial_app.domain.currencies import MissingNbpRateError, NbpRate
from financial_app.domain.formatting import format_date
from financial_app.domain.instruments import Instrument
from financial_app.domain.prices import YAHOO, PriceSourceError
from financial_app.domain.transactions import (
    PLN,
    Transaction,
    TransactionDraft,
    TransactionError,
    covering_deposits,
)
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.reconciliation import (
    Action,
    AddBroker,
    KeepMine,
    SkipBroker,
    apply_reconciliation,
    handled_broker_ids,
    unpaired_security_transfers,
)
from financial_app.persistence.settings import CRYPTO_ACCOUNT, CRYPTO_COIN, CRYPTO_WALLET, load_setting, save_setting
from financial_app.persistence.transactions import list_transactions
from financial_app.sources.spreadsheet import NbpLookup
from financial_app.sources.yahoo import YahooSource

# How far back a market price is looked for when the day itself has no close
PRICE_WINDOW_DAYS = 7

# A coin's market price in an Instrument's currency on a day: (Yahoo symbol, currency, day) -> price
PriceLookup = Callable[[str, str, date], Decimal]


@dataclass(frozen=True)
class CryptoFile:
    """The trades of one source's exports (every file of it in the folder) and what could not be read."""

    exchange: str
    trades: list[CryptoTrade]
    unsupported: list[Unsupported]
    transfers: list[CryptoTransfer] = field(default_factory=list)

    @property
    def is_wallet(self) -> bool:
        """A wallet's export (Trezor): its Account is the wallet, its transfers pair with saved ones."""
        return self.exchange == TREZOR


@dataclass(frozen=True)
class CryptoDecisions:
    """The user's choices: by source, the Account its trades go into and the wallet Account withdrawals are
    transferred to (missing: not chosen, the remembered one); an Instrument per coin symbol. For a wallet's export
    (Trezor): the other Account of each transfer that pairs with none, by external id, or the transfers ``skipped``;
    any other is left for later."""

    accounts: Mapping[str, int] = field(default_factory=dict)
    wallets: Mapping[str, int] = field(default_factory=dict)
    instruments: Mapping[str, int] = field(default_factory=dict)
    counterparts: Mapping[str, int] = field(default_factory=dict)
    skipped: frozenset[str] = frozenset()
    # The Accounts whose proposed deposits (``proposed_deposits``) the user declined
    no_deposits: frozenset[int] = frozenset()


@dataclass(frozen=True)
class Problem:
    trade: CryptoTrade
    message: str


@dataclass(frozen=True)
class CryptoPreview:
    file: CryptoFile
    account_id: int | None
    # The Account withdrawals go to; None when the file has none or it is not chosen yet
    wallet_id: int | None
    # Coins with no Instrument yet
    unmatched_coins: list[str]
    drafts: list[TransactionDraft]
    problems: list[Problem]
    # Trades imported before
    handled: int
    # The withdrawals not imported before
    transfers: list[CryptoTransfer]
    # The transfers that are the other side of a known Security Transfer, by external id: a saved Transaction, or the
    # draft another source of the same import adds
    pairs: dict[str, TransactionDraft] = field(default_factory=dict)
    # A wallet's export: its transfers with no other Account chosen, left for a later import, and those skipped
    later: list[CryptoTransfer] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.needs_choices or bool(self.problems)

    @property
    def needs_choices(self) -> bool:
        """The Account, the wallet or a coin's Instrument is still to be chosen."""
        return self.account_id is None or self.needs_wallet or bool(self.unmatched_coins)

    @property
    def needs_wallet(self) -> bool:
        """The exchange's file has withdrawals not imported before, and the Account they go to is not chosen."""
        return not self.file.is_wallet and bool(self.transfers) and self.wallet_id is None

    @property
    def unpaired(self) -> list[CryptoTransfer]:
        """A wallet's transfers not imported before that pair with none: each needs its other Account."""
        if not self.file.is_wallet or self.account_id is None:
            return []
        return [transfer for transfer in self.transfers if transfer.external_id not in self.pairs]

    @property
    def actions(self) -> list[Action]:
        """What applying saves: the drafts, the pairs with saved Transactions and the skipped transfers."""
        return [
            *(AddBroker(draft) for draft in self.drafts),
            *(
                KeepMine(known.id, external_id)
                for external_id, known in self.pairs.items()
                if isinstance(known, Transaction)
            ),
            *(SkipBroker(external_id) for external_id in self.skipped),
        ]


def read_crypto(path: Path) -> list[CryptoFile]:
    """The trades in a Binance, OKX or Trezor CSV file, or in the CSV files of a folder and its subfolders, one
    ``CryptoFile`` per source, the exchanges before the wallet; raises CryptoError if nothing can be read."""
    files = sorted(path.rglob("*.csv")) if path.is_dir() else [path]
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
            raise CryptoError(f"Plik {file.name} nie wygląda na eksport z Binance, OKX ani Trezora (CSV).")
    if not found:
        raise CryptoError(f"W folderze {path.name} nie ma plików z Binance, OKX ani Trezora.")
    order = list(EXCHANGE_NAMES)
    return [_file(exchange, found[exchange]) for exchange in sorted(found, key=lambda e: (e == TREZOR, order.index(e)))]


def _file(exchange: str, texts: list[str]) -> CryptoFile:
    """One source's exports merged; a row in two of them (a copy of a file) counts once."""
    read: CryptoRead = parse_exchange(exchange, texts)
    trades = list({trade.external_id: trade for trade in read.trades}.values())
    transfers = list({transfer.external_id: transfer for transfer in read.transfers}.values())
    return CryptoFile(exchange, trades, list(dict.fromkeys(read.unsupported)), transfers)


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


def _account(engine: Engine, exchange: str, decisions: CryptoDecisions, wallets: Iterable[int]) -> int | None:
    """The source's Account: chosen, remembered, or for the wallet's own export the wallet the exchanges' withdrawals
    go to (``wallets``: those chosen in this import), if they all chose one."""
    if (chosen := decisions.accounts.get(exchange)) is not None:
        return chosen
    if (saved := load_setting(engine, CRYPTO_ACCOUNT + exchange)) is not None:
        return int(saved)
    if exchange != TREZOR:
        return None
    remembered = (load_setting(engine, CRYPTO_WALLET + other) for other in EXCHANGE_NAMES if other != TREZOR)
    found = {*wallets, *(int(wallet) for wallet in remembered if wallet is not None)}
    return found.pop() if len(found) == 1 else None


def _wallet(engine: Engine, exchange: str, decisions: CryptoDecisions) -> int | None:
    if (chosen := decisions.wallets.get(exchange)) is not None:
        return chosen
    saved = load_setting(engine, CRYPTO_WALLET + exchange)
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
    engine: Engine, files: Sequence[CryptoFile], rates: NbpLookup, prices: PriceLookup, decisions: CryptoDecisions
) -> list[CryptoPreview]:
    """Match each source's Account and coins and turn the trades not imported before into Transactions, without
    saving. A source's transfers pair with the saved ones and with those the sources before it add."""
    previews: list[CryptoPreview] = []
    for file in files:
        added = [draft for preview in previews for draft in preview.drafts]
        # A saved transfer another source pairs with is no longer the other side of this one's
        claimed = {
            known.id for preview in previews for known in preview.pairs.values() if isinstance(known, Transaction)
        }
        wallets = [preview.wallet_id for preview in previews if preview.wallet_id is not None]
        previews.append(_preview(engine, file, rates, prices, decisions, added, claimed, wallets))
    return previews


def _preview(
    engine: Engine,
    file: CryptoFile,
    rates: NbpLookup,
    prices: PriceLookup,
    decisions: CryptoDecisions,
    added: list[TransactionDraft],
    claimed: set[int],
    wallets: list[int],
) -> CryptoPreview:
    instruments = {instrument.id: instrument for instrument in list_instruments(engine)}
    account_id = _account(engine, file.exchange, decisions, wallets)
    handled = handled_broker_ids(engine)
    trades = [trade for trade in file.trades if trade.external_id not in handled]
    transfers = [transfer for transfer in file.transfers if transfer.external_id not in handled]
    symbols = [*(trade.symbol for trade in trades), *(transfer.symbol for transfer in transfers)]
    resolved = {symbol: _instrument(engine, symbol, instruments, decisions) for symbol in symbols}
    unmatched = [symbol for symbol, found in resolved.items() if found is None]

    wallet_id = _wallet(engine, file.exchange, decisions) if transfers and not file.is_wallet else None
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
    pairs: dict[str, TransactionDraft] = {}
    later: list[CryptoTransfer] = []
    skipped: list[str] = []
    if account_id is not None and (wallet_id is not None or file.is_wallet):
        instrument_ids = {symbol: found.id for symbol, found in resolved.items() if found is not None}
        saved = [t for t in unpaired_security_transfers(engine, account_id) if t.id not in claimed]
        pairs = pair_transfers(transfers, [*saved, *added], account_id, wallet_id, instrument_ids)
        for transfer in transfers:
            found = resolved[transfer.symbol]
            if found is None or transfer.external_id in pairs:
                continue
            other = wallet_id if wallet_id is not None else decisions.counterparts.get(transfer.external_id)
            if transfer.external_id in decisions.skipped:
                skipped.append(transfer.external_id)
            # The wallet's own Account, chosen as the other one before it became the wallet's, is no choice
            elif other is not None and other != account_id:
                drafts.append(transfer_draft(transfer, account_id, other, found))
            else:
                later.append(transfer)
    done = len(file.trades) + len(file.transfers) - len(trades) - len(transfers)
    return CryptoPreview(
        file,
        account_id,
        wallet_id,
        unmatched,
        drafts,
        problems,
        done,
        transfers,
        pairs=pairs,
        later=later,
        skipped=skipped,
    )


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
    files: Sequence[CryptoFile],
    rates: NbpLookup,
    prices: PriceLookup,
    decisions: CryptoDecisions,
    today: date,
) -> list[CryptoPreview]:
    """Save every new trade of every source, all or none, and remember the matches; returns what was applied.

    Raises CryptoError if an Account or a coin is unmatched or a trade cannot become a Transaction; nothing is saved
    then.
    """
    previews = preview_crypto(engine, files, rates, prices, decisions)
    if any(preview.needs_choices for preview in previews):
        raise CryptoError("Wybierz konto, konto portfela dla wypłat i instrument dla każdej monety.")
    for preview in previews:
        if preview.problems:
            first = preview.problems[0]
            raise CryptoError(f"Transakcja z {format_date(first.trade.day)}: {first.message}")
    deposits = [AddBroker(deposit) for deposit in kept_deposits(engine, previews, decisions)]
    apply_reconciliation(engine, [*_actions(previews), *deposits], today)
    for preview in previews:
        save_setting(engine, CRYPTO_ACCOUNT + preview.file.exchange, str(preview.account_id))
        if preview.wallet_id is not None:
            save_setting(engine, CRYPTO_WALLET + preview.file.exchange, str(preview.wallet_id))
    for symbol, instrument_id in decisions.instruments.items():
        save_setting(engine, CRYPTO_COIN + symbol, str(instrument_id))
    return previews


def proposed_deposits(engine: Engine, previews: Sequence[CryptoPreview]) -> dict[int, list[TransactionDraft]]:
    """The Deposits that keep the cash of each Account of the import from going below zero, by Account id, after what
    is saved and what the import adds: an exchange's export has no PLN deposits (a Binance purchase "With Fiat" was
    paid by card, OKX's stablecoin deposits are left out), so its purchases would take the cash below zero."""
    known = [*list_transactions(engine), *(draft for preview in previews for draft in preview.drafts)]
    accounts = dict.fromkeys(preview.account_id for preview in previews if preview.account_id is not None)
    proposed = {account_id: covering_deposits(known, account_id) for account_id in accounts}
    return {account_id: deposits for account_id, deposits in proposed.items() if deposits}


def kept_deposits(
    engine: Engine, previews: Sequence[CryptoPreview], decisions: CryptoDecisions
) -> list[TransactionDraft]:
    """The proposed Deposits applying saves: those of the Accounts the user did not decline."""
    proposed = proposed_deposits(engine, previews)
    return [d for account_id, deposits in proposed.items() if account_id not in decisions.no_deposits for d in deposits]


def _actions(previews: Sequence[CryptoPreview]) -> list[Action]:
    """Every source's actions; a transfer another source pairs with in the same import is added with its id."""
    linked = {
        known.external_id: external_id
        for preview in previews
        for external_id, known in preview.pairs.items()
        if not isinstance(known, Transaction)
    }
    return [
        AddBroker(action.draft, linked.get(action.draft.external_id or "")) if isinstance(action, AddBroker) else action
        for preview in previews
        for action in preview.actions
    ]
