"""The first-run window (#270): five steps from an empty database to a Portfolio, on the shared ``ui/wizard.py``.

The shell opens it at start while there is no Account and it was never closed (``FIRST_RUN_DISMISSED``); the header's
"Pierwsze kroki" chip (#288), shown while a step is not done, and Ustawienia > Konta reopen it on the first step not
done. The Konta step adds Accounts through the Account form; the other steps explain and go to the screen that does
the job (Ustawienia > Import, the Transaction form, Ustawienia > Instrumenty). Which steps are done comes from the
data, so it holds for a database set up before the window existed too.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from nicegui import ui
from sqlalchemy import Engine

from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.settings import (
    FIRST_RUN_CHIP_HIDDEN,
    FIRST_RUN_DISMISSED,
    load_setting,
    save_setting,
)
from financial_app.persistence.transactions import list_transactions
from financial_app.sources.prices import unpriced_instruments
from financial_app.ui.accounts import open_account_dialog
from financial_app.ui.wizard import Wizard, WizardStep

WELCOME = (
    "KAPITA prowadzi Twój portfel inwestycyjny: transakcje, pozycje, wyceny i wyniki wszystkich kont razem, z "
    "dochodem pasywnym, obligacjami skarbowymi i limitami wpłat na IKE i IKZE. Twoje dane zostają na tym komputerze, "
    "w bazie w folderze aplikacji; z internetu KAPITA pobiera tylko notowania, kursy walut i dane obligacji."
)
ACCOUNTS = (
    "Konto to rachunek, na którym trzymasz inwestycje: maklerskie (typ Regular), IKE, IKZE, OIPE, PPK, lokata, "
    "obligacje skarbowe albo inne. Typ konta decyduje o podatku: na zwykłym koncie 19% podatku Belki od zysku przy "
    "sprzedaży, IKE i OIPE zwalniają z niego przy wypłacie spełniającej warunki, a wpłaty na IKZE odliczasz od "
    "dochodu. Wpłaty na IKE, IKZE i OIPE mają roczne limity: KAPITA liczy, ile zostało, w Ustawienia > Limity i reguły."
)
HISTORY = (
    "Pozycje i wyniki KAPITA liczy z historii transakcji. Możesz ją wczytać z zestawień XTB albo z eksportów giełd "
    "kryptowalut (oba w Ustawienia > Import; konta dla nich utworzysz przy imporcie) albo wpisać transakcje ręcznie: "
    "przyciskiem „+” w prawym dolnym rogu albo w zakładce Transakcje."
)
PRICES = (
    "Wyceny pobierają się same przy starcie, gdy minęło zamknięcie sesji, i przyciskiem odświeżania w nagłówku: "
    "zagraniczne akcje, ETF-y i kryptowaluty z Yahoo Finance, akcje, ETF-y i obligacje z GPW z Bossy, fundusze i PPK "
    "z analizy.pl i bankier.pl, kursy walut z NBP, a obligacje skarbowe z danych Ministerstwa Finansów. Nie "
    "potrzebujesz żadnego klucza. Źródło i symbol instrumentu zmienisz w Ustawienia "
    "> Instrumenty; tam też widać instrumenty bez automatycznej ceny, którym wpiszesz cenę ręcznie."
)
WHERE = (
    ("Dashboard", "wartość portfela, wynik i wykresy w czasie"),
    ("Portfolio", "pozycje z wyceną i wynikiem każdej"),
    ("Transakcje", "lista transakcji z filtrami, edycja i szkice reguł cyklicznych"),
    ("Ustawienia", "konta, instrumenty, import, limity i wygląd"),
)


@dataclass
class FirstRunWizard:
    """The window. ``open_settings`` shows an Ustawienia section by its key and ``add_transaction`` opens the
    Transaction form, with what to do once it saved one."""

    engine: Engine
    open_settings: Callable[[str], None]
    add_transaction: Callable[[Callable[[], None]], None]
    # Runs after an Account is added here: the Ustawienia page drawn last sets it to redraw its Konta list, whichever
    # button opened the window
    on_accounts_changed: Callable[[], object] | None = field(default=None, init=False)
    # Runs when a step may have been done or the chip closed, e.g. to redraw the header's chip
    on_progress: Callable[[], object] | None = None
    wizard: Wizard | None = None

    def open_if_new(self) -> None:
        """Open the window on a database with no Account, unless it was closed before."""
        if load_setting(self.engine, FIRST_RUN_DISMISSED) is None and not list_accounts(self.engine):
            self.open()

    def open(self) -> None:
        """Open the window on the first step not done; on the welcome while none is, or once all are."""
        if self.wizard is None:
            steps = (
                WizardStep("Witaj w KAPITA", self._welcome),
                WizardStep("Konta", self._accounts, self._has_account),
                WizardStep("Historia transakcji", self._history, self._has_transaction),
                WizardStep("Wyceny", self._prices, self._all_priced),
                WizardStep("Gotowe", self._done),
            )
            # On the page itself, so that it outlives the tab it is opened from
            with ui.context.client.content:
                self.wizard = Wizard("first-run", steps, width="w-[44rem]")
            # However it closes (Zamknij, a button below, Esc), it never opens by itself again
            self.wizard.dialog.on_value_change(lambda e: None if e.value else self._dismiss())
        self.wizard.open(self._first_step())

    def _first_step(self) -> int:
        assert self.wizard is not None
        checked = [(number, step.done()) for number, step in enumerate(self.wizard.steps, 1) if step.done is not None]
        if not any(done for _, done in checked):
            return 1
        return next((number for number, done in checked if not done), 1)

    def progress(self) -> tuple[int, int]:
        """How many of the steps with a job are done, of how many."""
        done = [self._has_account(), self._has_transaction(), self._all_priced()]
        return sum(done), len(done)

    def _has_account(self) -> bool:
        return bool(list_accounts(self.engine))

    def _has_transaction(self) -> bool:
        return bool(list_transactions(self.engine))

    def _all_priced(self) -> bool:
        """Every held Instrument has a price, once there is a Transaction: none is in "Instrumenty bez wyceny" but
        those with a Manual Price."""
        return self._has_transaction() and all(
            unpriced.instrument.manual_price is not None for unpriced in unpriced_instruments(self.engine)
        )

    def chip(self) -> None:
        """The header's "Pierwsze kroki n/3" chip opening the window, while a step is not done and it was not closed
        with its ×; the shell redraws it through ``on_progress``."""
        if load_setting(self.engine, FIRST_RUN_CHIP_HIDDEN) is not None:
            return
        done, of = self.progress()
        if done == of:
            return
        with ui.row().classes("items-center gap-0 no-wrap").mark("first-run-chip"):
            ui.button(f"Pierwsze kroki {done}/{of}", icon="explore", on_click=self.open).props(
                "flat no-caps no-wrap color=ink"
            ).mark("first-run-chip-open")
            ui.button(icon="close", on_click=self._hide_chip).props(
                'flat round dense size=sm color=ink aria-label="Ukryj pierwsze kroki"'
            ).tooltip("Ukryj; okno otworzysz w Ustawienia > Konta").mark("first-run-chip-hide")

    def _hide_chip(self) -> None:
        save_setting(self.engine, FIRST_RUN_CHIP_HIDDEN, "1")
        self.progress_changed()

    def progress_changed(self) -> None:
        if self.on_progress is not None:
            self.on_progress()

    def _dismiss(self) -> None:
        save_setting(self.engine, FIRST_RUN_DISMISSED, "1")

    def _go(self, action: Callable[[], None]) -> None:
        """Close the window and do ``action`` on the page, whose dialogs outlive the window's body."""
        assert self.wizard is not None
        self.wizard.close()
        with ui.context.client.content:
            action()

    def _welcome(self) -> bool:
        ui.label(WELCOME).classes("text-sm")
        ui.label(
            "Kilka kroków pokaże, od czego zacząć; te już zrobione mają znaczek ✓. Okno zamkniesz w każdej chwili, a "
            "wrócisz do niego przyciskiem „Pierwsze kroki” u góry okna albo w Ustawienia > Konta."
        ).classes("text-sm k-muted")
        return True

    def _accounts(self) -> bool:
        ui.label(ACCOUNTS).classes("text-sm")
        with ui.column().classes("w-full gap-0").mark("first-run-accounts"):
            accounts = list_accounts(self.engine)
            if not accounts:
                ui.label("Nie dodano jeszcze żadnego konta.").classes("k-muted")
            for account in accounts:
                ui.label(f"{account.name} · {account.account_type.label}").classes("font-medium")
        ui.button("Dodaj nowe konto", icon="add", on_click=self._add_account).props("no-caps").mark(
            "first-run-add-account"
        )
        return True

    def _add_account(self) -> None:
        with ui.context.client.content:
            open_account_dialog(self.engine, None, on_saved=lambda _: self._account_added())

    def _account_added(self) -> None:
        assert self.wizard is not None
        self.wizard.render()
        # The Konta list's redraw tells the chip too
        if self.on_accounts_changed is not None:
            self.on_accounts_changed()
        else:
            self.progress_changed()

    def _history(self) -> bool:
        ui.label(HISTORY).classes("text-sm")
        with ui.row().classes("gap-2"):
            ui.button(
                "Import z XTB lub kryptowalut",
                icon="upload_file",
                on_click=lambda: self._go(lambda: self.open_settings("import")),
            ).props("no-caps").mark("first-run-import")
            ui.button(
                "Wpisz transakcję ręcznie",
                icon="edit",
                on_click=lambda: self._go(lambda: self.add_transaction(self._transaction_saved)),
            ).props("no-caps flat").mark("first-run-add-transaction")
        return True

    def _transaction_saved(self) -> None:
        """Back to the window, on the step that is next to do."""
        assert self.wizard is not None
        self.wizard.open(self._first_step())

    def _prices(self) -> bool:
        ui.label(PRICES).classes("text-sm")
        ui.button(
            "Przejdź do instrumentów", icon="list", on_click=lambda: self._go(lambda: self.open_settings("instruments"))
        ).props("no-caps flat").mark("first-run-instruments")
        return True

    def _done(self) -> bool:
        ui.label("Gotowe. Tu znajdziesz resztę:").classes("text-sm")
        for tab, what in WHERE:
            ui.label(f"{tab}: {what}.").classes("text-sm")
        ui.label(
            "To okno otworzysz znowu przyciskiem „Pierwsze kroki” u góry okna, dopóki któryś krok czeka, albo w "
            "Ustawienia > Konta."
        ).classes("text-sm k-muted").mark("first-run-done")
        return True
