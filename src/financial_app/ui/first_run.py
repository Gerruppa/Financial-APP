"""The first-run window (#270): five steps from an empty database to a Portfolio, on the shared ``ui/wizard.py``.

The shell opens it at start while there is no Account and it was never closed (``FIRST_RUN_DISMISSED``); Ustawienia >
Konta reopens it with "Pierwsze kroki". The Konta step adds Accounts through the Account form; the other steps explain
and go to the screen that does the job (Ustawienia > Import, the Transaction form, Ustawienia > Instrumenty).
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from nicegui import ui
from sqlalchemy import Engine

from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.settings import FIRST_RUN_DISMISSED, load_setting, save_setting
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
    Transaction form."""

    engine: Engine
    open_settings: Callable[[str], None]
    add_transaction: Callable[[], None]
    # Runs after an Account is added here, e.g. to redraw the Konta list the window was reopened from
    on_accounts_changed: Callable[[], object] | None = field(default=None, init=False)
    wizard: Wizard | None = None

    def open_if_new(self) -> None:
        """Open the window on a database with no Account, unless it was closed before."""
        if load_setting(self.engine, FIRST_RUN_DISMISSED) is None and not list_accounts(self.engine):
            self.open()

    def open(self, on_accounts_changed: Callable[[], object] | None = None) -> None:
        self.on_accounts_changed = on_accounts_changed
        if self.wizard is None:
            steps = (
                WizardStep("Witaj w KAPITA", self._welcome),
                WizardStep("Konta", self._accounts),
                WizardStep("Historia transakcji", self._history),
                WizardStep("Wyceny", self._prices),
                WizardStep("Gotowe", self._done),
            )
            # On the page itself, so that it outlives the tab it is opened from
            with ui.context.client.content:
                self.wizard = Wizard("first-run", steps, width="w-[44rem]")
            # However it closes (Zamknij, a button below, Esc), it never opens by itself again
            self.wizard.dialog.on_value_change(lambda e: None if e.value else self._dismiss())
        self.wizard.open()

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
            "Kilka kroków pokaże, od czego zacząć. Okno zamkniesz w każdej chwili, a otworzysz je znowu przyciskiem "
            "„Pierwsze kroki” w Ustawienia > Konta."
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
        if self.on_accounts_changed is not None:
            self.on_accounts_changed()

    def _history(self) -> bool:
        ui.label(HISTORY).classes("text-sm")
        with ui.row().classes("gap-2"):
            ui.button(
                "Import z XTB lub kryptowalut",
                icon="upload_file",
                on_click=lambda: self._go(lambda: self.open_settings("import")),
            ).props("no-caps").mark("first-run-import")
            ui.button("Wpisz transakcję ręcznie", icon="edit", on_click=lambda: self._go(self.add_transaction)).props(
                "no-caps flat"
            ).mark("first-run-add-transaction")
        return True

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
        ui.label("To okno otworzysz znowu przyciskiem „Pierwsze kroki” w Ustawienia > Konta.").classes(
            "text-sm k-muted"
        ).mark("first-run-done")
        return True
