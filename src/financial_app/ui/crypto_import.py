"""Ustawienia > Import z giełdy kryptowalut: Binance and OKX CSV exports as Transactions (spec 7).

The user points at the exported file (or the folder of OKX's files), chooses the Account and an Instrument for each
coin, sees the Transactions to be added and applies them. Nothing is saved until "Zastosuj".
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path as FilePath

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.accounts import Account
from financial_app.domain.crypto_import import EXCHANGE_NAMES
from financial_app.domain.formatting import format_count, format_date
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


@dataclass
class CryptoImportSection:
    """Reads an export, lets the user match its Account and coins, and applies on approval.

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
    file: CryptoFile | None = None
    account_id: int | None = None
    wallet_id: int | None = None
    instruments: dict[str, int] = field(default_factory=dict)

    def build(self) -> None:
        self.card = ui.card().classes("w-full max-w-4xl")
        with self.card:
            ui.label("Import z giełdy kryptowalut").classes("text-xl font-bold")
            ui.label(
                "Wskaż plik CSV z Binance (Historia transakcji) albo z OKX (Order History; może być cały folder "
                "eksportu). Binance nie podaje cen, więc ceny BTC są pobierane z Yahoo z dnia transakcji; USDC z OKX "
                "liczymy jak USD po kursie NBP. Nic nie jest zapisywane przed „Zastosuj”."
            ).classes("text-sm")
            path = ui.input("Plik albo folder z eksportem giełdy").classes("w-full").mark("crypto-path")
            ui.button("Wczytaj", icon="visibility", on_click=lambda: self.load(path.value)).props("no-caps").mark(
                "crypto-load"
            )
            self.result = ui.column().classes("w-full gap-2").mark("crypto-result")

    def load(self, text: str) -> None:
        try:
            self.file = read_crypto(FilePath(text.strip()))
        except TransactionError as error:
            self.result.clear()
            ui.notify(str(error), type="negative")
            return
        self.account_id = None
        self.wallet_id = None
        self.instruments = {}
        self.render()

    def reset(self) -> None:
        """Forget the file and choices, e.g. after the data was cleared: they name removed ids."""
        self.file = None
        self.account_id = None
        self.wallet_id = None
        self.instruments = {}
        self.result.clear()

    def _decisions(self) -> CryptoDecisions:
        return CryptoDecisions(self.account_id, self.wallet_id, dict(self.instruments))

    def render(self) -> None:
        assert self.file is not None
        preview = preview_crypto(self.engine, self.file, self.rates, self.prices, self._decisions())
        names = {account.id: account.name for account in list_accounts(self.engine)}
        instruments = list_instruments(self.engine)
        self.result.clear()
        with self.result:
            self._account(preview, names)
            self._wallet(preview, names)
            self._coins(preview, instruments)
            if preview.account_id is None or preview.needs_wallet or preview.unmatched_coins:
                ui.label("Wybierz konta i instrumenty, aby zobaczyć transakcje.").classes("k-muted")
                return
            for problem in preview.problems:
                ui.label(f"{format_date(problem.trade.day)}: {problem.message}").classes("text-negative").mark(
                    "crypto-problem"
                )
            ui.label(
                f"Do dodania: {len(preview.drafts)}, już zaimportowane: {preview.handled}, "
                f"nieobsługiwane: {len(preview.file.unsupported)}."
            ).mark("crypto-summary")
            describe = Describer(names, {instrument.id: instrument.name for instrument in instruments})
            for draft in preview.drafts:
                ui.label(describe(draft)).classes("text-sm").mark("crypto-item")
            if preview.file.unsupported:
                with (
                    ui.expansion(f"Nieobsługiwane operacje, do wpisania ręcznie ({len(preview.file.unsupported)})")
                    .classes("w-full")
                    .mark("crypto-unsupported")
                ):
                    for item in preview.file.unsupported:
                        ui.label(f"{format_date(item.day)}: {item.note}").classes("text-sm")
            apply = ui.button(f"Zastosuj ({len(preview.drafts)})", icon="save", on_click=self.apply).props("no-caps")
            apply.mark("crypto-apply")
            if preview.blocked or not preview.drafts:
                apply.disable()

    def _account(self, preview: CryptoPreview, names: dict[int, str]) -> None:
        options: dict[int | str, str] = {NEW: "+ Nowe konto…"}
        options.update(names.items())
        ui.select(
            options,
            value=preview.account_id,
            label=f"Konto dla importu z {EXCHANGE_NAMES[preview.file.exchange]}",
            on_change=lambda e: self._choose_account(e.value),
        ).classes("w-full").mark("crypto-account")

    def _wallet(self, preview: CryptoPreview, names: dict[int, str]) -> None:
        if not preview.transfers:
            return
        ui.select(
            names,
            value=preview.wallet_id,
            label="Konto portfela, na które trafiają wypłaty (przeniesienie papierów)",
            on_change=lambda e: self._choose_wallet(e.value),
        ).classes("w-full").mark("crypto-wallet")

    def _choose_wallet(self, choice: int | None) -> None:
        if choice is not None:
            self.wallet_id = int(choice)
            self.render()

    def _coins(self, preview: CryptoPreview, instruments: list[Instrument]) -> None:
        if not preview.unmatched_coins:
            return
        ui.label("Monety bez instrumentu w aplikacji (wybierz istniejący albo utwórz nowy):").classes("font-bold")
        options: dict[int | str, str] = {NEW: "+ Nowy instrument…"}
        options.update({instrument.id: instrument.name for instrument in instruments})
        for symbol in preview.unmatched_coins:
            ui.select(
                options,
                label=f"Moneta {symbol} to",
                on_change=lambda e, s=symbol: self._choose_instrument(s, e.value),
            ).classes("w-full").mark(f"crypto-instrument-{symbol}")

    def _choose_account(self, choice: int | str | None) -> None:
        if choice is None:
            return
        if choice == NEW:
            assert self.file is not None
            with self.card:
                open_account_dialog(
                    self.engine,
                    None,
                    on_saved=self._account_created,
                    name=EXCHANGE_NAMES[self.file.exchange],
                )
            self.render()
            return
        self.account_id = int(choice)
        self.render()

    def _account_created(self, account: Account) -> None:
        self.account_id = account.id
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
        assert self.file is not None
        file = self.file
        try:
            applied = checked_save(
                self.engine,
                lambda: apply_crypto(self.engine, file, self.rates, self.prices, self._decisions(), self.today()),
            )
        except TransactionError as error:
            ui.notify(str(error), type="negative")
            self.render()
            return
        count = format_count(len(applied.value.drafts), "transakcję", "transakcje", "transakcji")
        ui.notify(f"Zaimportowano {count} z giełdy.", type="positive")
        show_warnings(applied.warnings)
        if self.on_saved is not None:
            self.on_saved()
        self.render()
