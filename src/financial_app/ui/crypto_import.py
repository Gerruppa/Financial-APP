"""Ustawienia > Import z giełdy kryptowalut: Binance, OKX and Trezor CSV exports as Transactions (spec 7).

The card opens a window that leads the user through the import step by step (``STEPS``): how to get the exports,
pointing at a file or a folder of them (any sources, subfolders too), each source's Account and an Instrument for each
coin, the Deposits proposed where the purchases would take an Account's cash below zero, and the Transactions to be
added, applied all at once, with hints for correcting them by hand. A Trezor's transfer that pairs with none is left
for later unless the user chooses its other Account or "Pomiń". Nothing is saved until "Zastosuj".
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
from financial_app.domain.transactions import COVERING_COMMENT, TransactionError
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.sources.crypto import (
    CryptoDecisions,
    CryptoFile,
    CryptoPreview,
    PriceLookup,
    apply_crypto,
    kept_deposits,
    preview_crypto,
    proposed_deposits,
    read_crypto,
    yahoo_prices,
)
from financial_app.sources.spreadsheet import NbpLookup
from financial_app.sources.transaction_saving import checked_save
from financial_app.sources.yahoo import YahooSource
from financial_app.ui.accounts import open_account_dialog
from financial_app.ui.save_warnings import deposit_choices, deposits_total, show_warnings
from financial_app.ui.wizard import Wizard, WizardStep
from financial_app.ui.xtb_import import NEW, Describer

OpenInstrument = Callable[..., None]
# The choices for a wallet's transfer that pairs with none: leave it for a later import, or never add it
LATER = "later"
SKIP = "skip"

STEPS = ("Pobierz eksporty", "Wskaż pliki", "Konta i monety", "Uzupełnienia", "Podgląd i zapis")
# Step 1: how to get the exports; general, as the exchanges' menus change
INSTRUCTIONS = (
    (
        "Załóż konta",
        "Po jednym koncie na każdą giełdę (np. „Binance”, „OKX”) i jedno na portfel sprzętowy („Trezor”). Możesz "
        "to zrobić też w kroku 3, przez „+ Nowe konto…”.",
    ),
    (
        "Binance",
        "Pobierz historię transakcji (Transaction History) za cały okres, w formacie CSV. Binance nie podaje w niej "
        "cen, więc aplikacja weźmie kurs zamknięcia z Yahoo z dnia transakcji.",
    ),
    (
        "OKX",
        "Pobierz trzy pliki CSV: historię zleceń (Order History), szczegóły transakcji (Trade Details) i historię "
        "rachunku (Funding History). Jeśli przyjdą w archiwum ZIP, rozpakuj je. Zlecenia w USDC aplikacja liczy jak "
        "w USD, po kursie NBP.",
    ),
    ("Trezor Suite", "Na koncie każdej monety wyeksportuj transakcje do pliku CSV."),
    (
        "Jeden folder",
        "Wrzuć wszystkie pliki do jednego folderu, np. Dokumenty\\Krypto. Podfoldery i kopie plików nie przeszkadzają: "
        "powtórzony wiersz liczy się raz. Przy kolejnym imporcie dołóż nowsze eksporty i wczytaj folder ponownie; "
        "to, co już zaimportowane, jest pomijane.",
    ),
    (
        "Instrumenty",
        "Każda moneta potrzebuje w aplikacji instrumentu z symbolem Yahoo, np. BTC-USD; wtedy dopasuje się sama. "
        "Brakujący utworzysz w kroku 3.",
    ),
)
# Step 5: what the import cannot know, for correcting it by hand afterwards
HINTS = (
    f"Wpłaty uzupełniające mają komentarz „{COVERING_COMMENT}”: znajdziesz je w Transakcjach i poprawisz ich datę "
    "albo kwotę, jeśli wiesz, kiedy i ile naprawdę wpłacałeś.",
    "Ceny zakupów z Binance to kurs zamknięcia z Yahoo z dnia transakcji, a nie cena, którą zapłaciłeś. Jeśli ją znasz "
    "(np. z wyciągu karty), popraw ją w Transakcjach.",
    "Operacje z listy nieobsługiwanych dodaj ręcznie przyciskiem + w Transakcjach: monety przeniesione między kontami "
    "to Transfer papierów, opłata pobrana w gotówce to Koszty.",
    "Przeniesienia z Trezora zostawione na później wrócą przy następnym imporcie; gdy dołożysz nowszy eksport giełdy, "
    "sparują się same.",
    "Opłaty sieciowe są zapisane jako sprzedaż monet z prowizją równą ich wartości, więc obniżają wynik: tak ma być.",
    "Na koniec porównaj w Portfelu liczbę monet na każdym koncie z saldem na giełdzie i w Trezor Suite; różnicę "
    "zwykle tłumaczy brakujący albo starszy eksport.",
)


@dataclass
class CryptoImportSection:
    """The import window: reads the exports, lets the user match each source's Account and the coins, proposes the
    missing Deposits and applies on approval.

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
    # The Accounts whose proposed Deposits the user declined
    no_deposits: set[int] = field(default_factory=set)
    # The window: the path typed, and whether this import was applied
    path: str = ""
    done: bool = False

    def build(self) -> None:
        self.card = ui.card().classes("w-full max-w-4xl")
        with self.card:
            ui.label("Import z giełdy kryptowalut").classes("text-xl font-bold")
            ui.label(
                "Binance, OKX i Trezor: okno poprowadzi Cię krok po kroku, od pobrania eksportów po uzupełnienie "
                "brakujących wpłat. Nic nie jest zapisywane przed „Zastosuj”."
            ).classes("text-sm")
            ui.button("Otwórz kreator importu kryptowalut", icon="currency_bitcoin", on_click=self.open).props(
                "no-caps"
            ).mark("crypto-open")
            # Opened from the card, which outlives it; each step in the order of STEPS
            bodies = (self._instructions, self._choose_files, self._choices, self._deposits, self._review)
            self.wizard = Wizard("crypto", [WizardStep(title, body) for title, body in zip(STEPS, bodies, strict=True)])

    def open(self) -> None:
        self.done = False
        self.wizard.open()

    def load(self, text: str) -> None:
        self.path = text
        try:
            self.files = read_crypto(FilePath(text.strip()))
        except TransactionError as error:
            ui.notify(str(error), type="negative")
            return
        self._forget_choices()
        self.wizard.go(3)

    def reset(self) -> None:
        """Forget the files and choices, e.g. after the data was cleared: they name removed ids."""
        self.files = []
        self._forget_choices()
        self.wizard.step = 1
        self.wizard.close()

    def _forget_choices(self) -> None:
        self.accounts = {}
        self.wallets = {}
        self.instruments = {}
        self.counterparts = {}
        self.skipped = set()
        self.no_deposits = set()
        self.done = False

    def _decisions(self) -> CryptoDecisions:
        return CryptoDecisions(
            dict(self.accounts),
            dict(self.wallets),
            dict(self.instruments),
            dict(self.counterparts),
            frozenset(self.skipped),
            frozenset(self.no_deposits),
        )

    def render(self) -> None:
        self.wizard.render()

    def _previews(self) -> list[CryptoPreview]:
        return preview_crypto(self.engine, self.files, self.rates, self.prices, self._decisions()) if self.files else []

    def _names(self) -> dict[int, str]:
        return {account.id: account.name for account in list_accounts(self.engine)}

    def _instructions(self) -> bool:
        ui.label("Zanim zaczniesz, przygotuj eksporty:").classes("text-sm")
        for number, (title, text) in enumerate(INSTRUCTIONS, start=1):
            with ui.row().classes("w-full no-wrap gap-2"):
                ui.label(f"{number}.").classes("font-bold")
                with ui.column().classes("gap-0"):
                    ui.label(title).classes("font-bold")
                    ui.label(text).classes("text-sm")
        return True

    def _choose_files(self) -> bool:
        ui.label("Wskaż plik CSV albo folder z eksportami z Binance, OKX i Trezora (także w podfolderach).").classes(
            "text-sm"
        )
        path = ui.input("Plik albo folder z eksportami", value=self.path).classes("w-full").mark("crypto-path")
        ui.button("Wczytaj", icon="visibility", on_click=lambda: self.load(path.value)).props("no-caps").mark(
            "crypto-load"
        )
        if self.files:
            found = ", ".join(EXCHANGE_NAMES[file.exchange] for file in self.files)
            ui.label(f"Wczytane: {found}.").classes("text-sm").mark("crypto-loaded")
        return bool(self.files)

    def _choices(self) -> bool:
        previews, names = self._previews(), self._names()
        for preview in previews:
            self._source(preview, names)
        self._coins(previews, list_instruments(self.engine))
        if any(preview.needs_choices for preview in previews):
            ui.label("Wybierz konta i instrumenty, aby przejść dalej.").classes("k-muted")
            return False
        return True

    def _deposits(self) -> bool:
        """The Deposits proposed where the purchases would take an Account's cash below zero, one checkbox per
        Account; and how many wallet transfers are left for later."""
        previews, names = self._previews(), self._names()
        ui.label(
            "Eksporty giełd nie zawierają wpłat złotówek (zakup „With Fiat” na Binance to płatność kartą, wpłaty USDC "
            "na OKX są pomijane), więc zakupy zdjęłyby gotówkę z konta poniżej zera. Aplikacja proponuje wpłaty "
            "w dniach, w których brakuje gotówki, dokładnie na brakującą kwotę. Odznacz konto, jeśli wpłaty "
            "wpiszesz sam."
        ).classes("text-sm")
        proposed = proposed_deposits(self.engine, previews)
        if not proposed:
            ui.label("Gotówka na kontach importu nie spada poniżej zera: nic do uzupełnienia.").mark(
                "crypto-no-deposits"
            )
        deposit_choices(proposed, names, lambda a: a not in self.no_deposits, self._keep_deposits, "crypto-deposits")
        later = sum(len(preview.later) for preview in previews)
        if later:
            transfers = format_count(later, "przeniesienie", "przeniesienia", "przeniesień")
            ui.label(
                f"{transfers} z Trezora zostaje na później; możesz wrócić do kroku 3 i wybrać drugie konto."
            ).classes("text-sm").mark("crypto-later")
        return True

    def _keep_deposits(self, account_id: int, keep: bool) -> None:
        if keep:
            self.no_deposits.discard(account_id)
        else:
            self.no_deposits.add(account_id)

    def _review(self) -> bool:
        previews, names = self._previews(), self._names()
        if self.done:
            ui.label("Zapisano. Sprawdź jeszcze wskazówki poniżej.").classes("text-positive font-bold").mark(
                "crypto-done"
            )
        if any(preview.needs_choices for preview in previews):
            ui.label("Wróć do kroku 3 i wybierz konta i instrumenty.").classes("k-muted")
            return False
        describe = Describer(names, {instrument.id: instrument.name for instrument in list_instruments(self.engine)})
        for preview in previews:
            self._summary(preview, describe)
        deposits = kept_deposits(self.engine, previews, self._decisions())
        if deposits:
            ui.label(f"Uzupełnienia: {deposits_total(deposits)}.").mark("crypto-deposits-summary")
        actions = sum(len(preview.actions) for preview in previews) + len(deposits)
        apply = ui.button(f"Zastosuj ({actions})", icon="save", on_click=self.apply).props("no-caps")
        apply.mark("crypto-apply")
        if any(preview.blocked for preview in previews) or not actions:
            apply.disable()
        with ui.expansion("Wskazówki do ręcznych poprawek", value=True).classes("w-full").mark("crypto-hints"):
            for hint in HINTS:
                ui.label(f"• {hint}").classes("text-sm")
        return True

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
        show_warnings(applied.warnings, engine=self.engine, on_saved=self.on_saved)
        if self.on_saved is not None:
            self.on_saved()
        self.done = True
        self.render()
