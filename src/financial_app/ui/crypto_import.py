"""Ustawienia > Import z giełdy kryptowalut: Binance, OKX and Trezor CSV exports as Transactions (spec 7).

The user points at an exported file or a folder of them (any sources, subfolders too), chooses each source's Account
and an Instrument for each coin, sees the Transactions to be added and applies them all at once. A Trezor's transfer
that pairs with none is left for later unless the user chooses its other Account or "Pomiń". Nothing is saved until
"Zastosuj".
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path as FilePath

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.accounts import Account
from financial_app.domain.crypto_import import EXCHANGE_NAMES
from financial_app.domain.formatting import format_count, format_date, format_quantity
from financial_app.domain.instruments import Instrument
from financial_app.domain.transactions import TransactionError
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.sources.crypto import (
    CryptoDecisions,
    CryptoFile,
    CryptoPreview,
    PriceLookup,
    apply_crypto,
    preview_crypto,
    read_crypto,
    yahoo_prices,
)
from financial_app.sources.spreadsheet import NbpLookup
from financial_app.sources.transaction_saving import checked_save
from financial_app.sources.yahoo import YahooSource
from financial_app.ui.accounts import open_account_dialog
from financial_app.ui.save_warnings import show_warnings
from financial_app.ui.xtb_import import NEW, Describer

OpenInstrument = Callable[..., None]
# The choices for a wallet's transfer that pairs with none: leave it for a later import, or never add it
LATER = "later"
SKIP = "skip"


@dataclass
class CryptoImportSection:
    """Reads the exports, lets the user match each source's Account and the coins, and applies on approval.

    ``open_instrument`` is the Instrument dialog (``InstrumentsSection.open_dialog``), for a coin without one;
    ``on_saved`` lets the other tabs redraw, ``on_account_added`` the Konta list after an Account is created here.
    ``prices`` gives the market price Binance's export lacks (Yahoo's daily closes unless a test passes its own).
    """

    engine: Engine
    rates: NbpLookup
    open_instrument: OpenInstrument
    on_saved: Callable[[], None] | None = None
    on_account_added: Callable[[], object] | None = None
    today: Callable[[], date] = date.today
    prices: PriceLookup = field(default_factory=lambda: yahoo_prices(YahooSource()))
    files: list[CryptoFile] = field(default_factory=list)
    # By source
    accounts: dict[str, int] = field(default_factory=dict)
    wallets: dict[str, int] = field(default_factory=dict)
    instruments: dict[str, int] = field(default_factory=dict)
    counterparts: dict[str, int] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)

    def build(self) -> None:
        self.card = ui.card().classes("w-full max-w-4xl")
        with self.card:
            ui.label("Import z giełdy kryptowalut").classes("text-xl font-bold")
            ui.label(
                "Wskaż plik CSV z Binance (Historia transakcji), z OKX (Order History, Trade Details, Funding "
                "History) albo z Trezor Suite, albo folder ze wszystkimi naraz (także w podfolderach). Binance nie "
                "podaje cen, więc ceny BTC są pobierane z Yahoo z dnia transakcji; USDC z OKX liczymy jak USD po "
                "kursie NBP. Przeniesienie między giełdą a portfelem, które jest w obu eksportach, zapisuje się raz. "
                "Nic nie jest zapisywane przed „Zastosuj”."
            ).classes("text-sm")
            path = ui.input("Plik albo folder z eksportami").classes("w-full").mark("crypto-path")
            ui.button("Wczytaj", icon="visibility", on_click=lambda: self.load(path.value)).props("no-caps").mark(
                "crypto-load"
            )
            self.result = ui.column().classes("w-full gap-2").mark("crypto-result")

    def load(self, text: str) -> None:
        try:
            self.files = read_crypto(FilePath(text.strip()))
        except TransactionError as error:
            self.result.clear()
            ui.notify(str(error), type="negative")
            return
        self._forget_choices()
        self.render()

    def reset(self) -> None:
        """Forget the files and choices, e.g. after the data was cleared: they name removed ids."""
        self.files = []
        self._forget_choices()
        self.result.clear()

    def _forget_choices(self) -> None:
        self.accounts = {}
        self.wallets = {}
        self.instruments = {}
        self.counterparts = {}
        self.skipped = set()

    def _decisions(self) -> CryptoDecisions:
        return CryptoDecisions(
            dict(self.accounts),
            dict(self.wallets),
            dict(self.instruments),
            dict(self.counterparts),
            frozenset(self.skipped),
        )

    def render(self) -> None:
        assert self.files
        previews = preview_crypto(self.engine, self.files, self.rates, self.prices, self._decisions())
        names = {account.id: account.name for account in list_accounts(self.engine)}
        instruments = list_instruments(self.engine)
        self.result.clear()
        with self.result:
            for preview in previews:
                self._source(preview, names)
            self._coins(previews, instruments)
            if any(preview.needs_choices for preview in previews):
                ui.label("Wybierz konta i instrumenty, aby zobaczyć transakcje.").classes("k-muted")
                return
            describe = Describer(names, {instrument.id: instrument.name for instrument in instruments})
            for preview in previews:
                self._summary(preview, describe)
            actions = sum(len(preview.actions) for preview in previews)
            apply = ui.button(f"Zastosuj ({actions})", icon="save", on_click=self.apply).props("no-caps")
            apply.mark("crypto-apply")
            if any(preview.blocked for preview in previews) or not actions:
                apply.disable()

    def _source(self, preview: CryptoPreview, names: dict[int, str]) -> None:
        """One source's choices: its Account, the wallet, and a Trezor's transfers that pair with none."""
        exchange = preview.file.exchange
        ui.label(EXCHANGE_NAMES[exchange]).classes("text-lg font-bold").mark(f"crypto-source-{exchange}")
        options: dict[int | str, str] = {NEW: "+ Nowe konto…"}
        options.update(names.items())
        ui.select(
            options,
            value=preview.account_id,
            label=f"Konto dla importu z {EXCHANGE_NAMES[exchange]}",
            on_change=lambda e: self._choose_account(exchange, e.value),
        ).classes("w-full").mark("crypto-account", f"crypto-account-{exchange}")
        self._wallet(preview, names)
        if preview.pairs or preview.skipped:
            ui.label(
                f"Sparowane z przeniesieniami z innych eksportów: {len(preview.pairs)}, "
                f"pominięte: {len(preview.skipped)}."
            ).mark("crypto-paired")
        self._counterparts(preview, names)

    def _summary(self, preview: CryptoPreview, describe: Describer) -> None:
        name = EXCHANGE_NAMES[preview.file.exchange]
        for problem in preview.problems:
            ui.label(f"{name}, {format_date(problem.trade.day)}: {problem.message}").classes("text-negative").mark(
                "crypto-problem"
            )
        ui.label(
            f"{name}: Do dodania: {len(preview.drafts)}, już zaimportowane: {preview.handled}, "
            f"nieobsługiwane: {len(preview.file.unsupported)}"
            + (f", na później: {len(preview.later)}." if preview.later else ".")
        ).mark("crypto-summary")
        for draft in preview.drafts:
            ui.label(describe(draft)).classes("text-sm").mark("crypto-item")
        if preview.file.unsupported:
            with (
                ui.expansion(f"{name}: nieobsługiwane operacje, do wpisania ręcznie ({len(preview.file.unsupported)})")
                .classes("w-full")
                .mark("crypto-unsupported")
            ):
                for item in preview.file.unsupported:
                    ui.label(f"{format_date(item.day)}: {item.note}").classes("text-sm")

    def _wallet(self, preview: CryptoPreview, names: dict[int, str]) -> None:
        if not preview.transfers or preview.file.is_wallet:
            return
        exchange = preview.file.exchange
        ui.select(
            names,
            value=preview.wallet_id,
            label="Konto portfela, na które trafiają wypłaty i z którego idą wpłaty (przeniesienie papierów)",
            on_change=lambda e: self._choose_wallet(exchange, e.value),
        ).classes("w-full").mark("crypto-wallet", f"crypto-wallet-{exchange}")

    def _choose_wallet(self, exchange: str, choice: int | None) -> None:
        if choice is not None:
            self.wallets[exchange] = int(choice)
            self.render()

    def _counterparts(self, preview: CryptoPreview, names: dict[int, str]) -> None:
        """A wallet's transfers that pair with none: the Account each came from or went to, "Pomiń", or "Później"
        (the default), when the exchange's export that explains it may have been read."""
        if not preview.unpaired:
            return
        ui.label(
            "Przeniesienia bez pary w innych eksportach (wybierz drugie konto, pomiń albo zostaw na później):"
        ).classes("font-bold")
        options: dict[int | str, str] = {LATER: "Później (do następnego importu)", SKIP: "Pomiń (nie dodawaj)"}
        options.update((i, name) for i, name in names.items() if i != preview.account_id)
        for transfer in preview.unpaired:
            key = transfer.external_id
            value: int | str = SKIP if key in self.skipped else self.counterparts.get(key, LATER)
            moved = f"{format_quantity(transfer.quantity)} {transfer.symbol}"
            label = f"{format_date(transfer.day)}: {'otrzymano' if transfer.incoming else 'wysłano'} {moved}"
            ui.select(
                options,
                value=value,
                label=f"{label}, {'z konta' if transfer.incoming else 'na konto'}",
                on_change=lambda e, k=key: self._choose_counterpart(k, e.value),
            ).classes("w-full").mark(f"crypto-counterpart-{key}")

    def _choose_counterpart(self, key: str, choice: int | str | None) -> None:
        if choice is None:
            return
        self.skipped.discard(key)
        self.counterparts.pop(key, None)
        if choice == SKIP:
            self.skipped.add(key)
        elif choice != LATER:
            self.counterparts[key] = int(choice)
        self.render()

    def _coins(self, previews: list[CryptoPreview], instruments: list[Instrument]) -> None:
        unmatched = list(dict.fromkeys(symbol for preview in previews for symbol in preview.unmatched_coins))
        if not unmatched:
            return
        ui.label("Monety bez instrumentu w aplikacji (wybierz istniejący albo utwórz nowy):").classes("font-bold")
        options: dict[int | str, str] = {NEW: "+ Nowy instrument…"}
        options.update({instrument.id: instrument.name for instrument in instruments})
        for symbol in unmatched:
            ui.select(
                options,
                label=f"Moneta {symbol} to",
                on_change=lambda e, s=symbol: self._choose_instrument(s, e.value),
            ).classes("w-full").mark(f"crypto-instrument-{symbol}")

    def _choose_account(self, exchange: str, choice: int | str | None) -> None:
        if choice is None:
            return
        if choice == NEW:
            with self.card:
                open_account_dialog(
                    self.engine,
                    None,
                    on_saved=lambda account: self._account_created(exchange, account),
                    name=EXCHANGE_NAMES[exchange],
                )
            self.render()
            return
        self.accounts[exchange] = int(choice)
        self.render()

    def _account_created(self, exchange: str, account: Account) -> None:
        self.accounts[exchange] = account.id
        if self.on_account_added is not None:
            self.on_account_added()
        self.render()

    def _choose_instrument(self, symbol: str, choice: int | str | None) -> None:
        if choice is None:
            return
        if choice == NEW:
            with self.card:
                self.open_instrument(
                    None, query=f"{symbol}-USD", on_saved=lambda i: self._instrument_created(symbol, i)
                )
            self.render()
            return
        self.instruments[symbol] = int(choice)
        self.render()

    def _instrument_created(self, symbol: str, instrument: Instrument) -> None:
        self.instruments[symbol] = instrument.id
        self.render()

    def apply(self) -> None:
        assert self.files
        files = self.files
        try:
            applied = checked_save(
                self.engine,
                lambda: apply_crypto(self.engine, files, self.rates, self.prices, self._decisions(), self.today()),
            )
        except TransactionError as error:
            ui.notify(str(error), type="negative")
            self.render()
            return
        added = sum(len(preview.drafts) for preview in applied.value)
        count = format_count(added, "transakcję", "transakcje", "transakcji")
        ui.notify(f"Zaimportowano {count} kryptowalut.", type="positive")
        show_warnings(applied.warnings)
        if self.on_saved is not None:
            self.on_saved()
        self.render()
