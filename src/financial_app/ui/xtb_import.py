"""Ustawienia > Import z XTB: XTB statements reconciled with the Transactions entered (spec 7, L-17).

The card opens a window that leads the user through the import step by step (``STEPS``, #271): which statements to
export, pointing at a file or a folder of them, matching each XTB account to an Account and each ticker to an
Instrument, then the Reconciliation one category at a time (the pairs that differ, the XTB-only and the entered-only
Transactions), each resolved as XTB has it by default, as XTB is the source of truth for its Accounts; the quantity
corrections and the Deposits proposed where the result would take an Account's cash below zero; and the preview,
applied all at once, with hints for correcting it by hand. Nothing is saved until "Zastosuj".
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path as FilePath

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.accounts import Account
from financial_app.domain.formatting import format_count, format_date, format_pln, format_quantity
from financial_app.domain.instruments import Instrument
from financial_app.domain.quantity_corrections import CORRECTION_COMMENT, Fix
from financial_app.domain.reconciliation import Choice, Pair, item_key
from financial_app.domain.transactions import COVERING_COMMENT, TransactionDraft, TransactionError
from financial_app.domain.xtb_import import XtbStatement, yahoo_symbol
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.sources.spreadsheet import NbpLookup
from financial_app.sources.transaction_saving import checked_save
from financial_app.sources.xtb import LEFT_OUT, XtbDecisions, XtbPreview, apply_xtb, preview_xtb, read_statements
from financial_app.ui.accounts import open_account_dialog
from financial_app.ui.quantity_corrections import HINT, correction_choices, corrections_total
from financial_app.ui.save_warnings import deposit_choices, deposits_total, show_warnings
from financial_app.ui.wizard import Wizard, WizardStep

NEW = "new"
PAIR_OPTIONS = {Choice.BROKER: "Weź XTB", Choice.MINE: "Zostaw moje"}
BROKER_ONLY_OPTIONS = {Choice.BROKER: "Dodaj", Choice.MINE: "Pomiń"}
MINE_ONLY_OPTIONS = {Choice.BROKER: "Usuń", Choice.MINE: "Zostaw"}

STEPS = (
    "Pobierz zestawienia",
    "Wskaż pliki",
    "Rachunki i tickery",
    "Różnice",
    "Tylko w XTB",
    "Tylko w aplikacji",
    "Uzupełnienia",
    "Podgląd i zapis",
)
# Step 1: which statements to export from xStation
INSTRUCTIONS = (
    (
        "Po jednym zestawieniu na rachunek",
        "W xStation wybierz rachunek (np. główny w PLN, IKE, IKZE), otwórz Historię konta i wyeksportuj ją. Każdy "
        "rachunek pobierz osobno; import obsługuje rachunki w PLN.",
    ),
    (
        "Format i okres",
        "Wybierz plik Excel (.xlsx), najlepiej za cały okres od otwarcia rachunku: zestawienie od późniejszego dnia "
        "nie ma wcześniejszych wpłat, więc aplikacja zaproponuje wpłaty uzupełniające.",
    ),
    (
        "Jeden folder",
        "Zapisz wszystkie zestawienia w jednym folderze, np. Dokumenty\\XTB. Wczytane razem, przelewy między "
        "rachunkami XTB (np. z głównego na IKE) staną się przelewami między kontami, a nie osobną wpłatą i wypłatą.",
    ),
    (
        "Konta i instrumenty",
        "Każdy rachunek XTB trafi na konto w aplikacji (IKE i IKZE dopasują się same, jeśli masz jedno takie konto), "
        "a każdy ticker na instrument. Brakujące utworzysz w kroku 3.",
    ),
    (
        "Uzgadnianie",
        "Operacje z XTB zostaną porównane z transakcjami wpisanymi na tych kontach. Domyślnie obowiązuje wersja XTB; "
        "w krokach 4–6 zdecydujesz o każdej różnicy. Nic nie jest zapisywane przed „Zastosuj”.",
    ),
)
# Step 8: what the import cannot know, for correcting it by hand afterwards
HINTS = (
    "Przy następnym eksporcie wczytaj ten sam folder z nowszymi zestawieniami: to, co już uzgodnione albo pominięte, "
    "nie wróci.",
    "Transakcje „tylko w aplikacji”, które zostawiłeś, zostają jako Twoje wpisy i nie wrócą przy następnym imporcie; "
    "usunięte znikają z Transakcji. Jeśli to był błąd, wpisz je ponownie przyciskiem + w Transakcjach.",
    f"Wpłaty uzupełniające mają komentarz „{COVERING_COMMENT}”: znajdziesz je w Transakcjach i poprawisz ich datę "
    "albo kwotę, jeśli wiesz, kiedy i ile wpłacałeś przed okresem zestawienia.",
    f"Zakupy dodane jako poprawka ilości mają komentarz „{CORRECTION_COMMENT}”. Jeśli znajdziesz brakujący zakup, "
    "usuń poprawkę i wpisz go.",
    "Dywidend z instrumentów w walucie obcej import nie czyta: taka dywidenda blokuje „Zastosuj” całego zestawienia. "
    "Pomiń wtedy ten rachunek w kroku 3 („Nie importuj”) i wpisz jego transakcje ręcznie w Transakcjach.",
    "Operacje z listy nieobsługiwanych dodaj ręcznie przyciskiem + w Transakcjach.",
    "Na koniec porównaj w Portfelu liczbę akcji i gotówkę na każdym koncie XTB z otwartymi pozycjami i saldem "
    "w xStation.",
)

OpenInstrument = Callable[..., None]


@dataclass
class XtbImportSection:
    """The import window: reads the statements, lets the user match and resolve, proposes the missing Deposits and
    applies on approval.

    ``open_instrument`` is the Instrument dialog (``InstrumentsSection.open_dialog``), for a ticker without one;
    ``on_saved`` lets the other tabs redraw, ``on_account_added`` the Konta list after an Account is created here.
    """

    engine: Engine
    rates: NbpLookup
    open_instrument: OpenInstrument
    on_saved: Callable[[], None] | None = None
    on_account_added: Callable[[], object] | None = None
    today: Callable[[], date] = date.today
    statements: list[XtbStatement] = field(default_factory=list)
    accounts: dict[str, int | None] = field(default_factory=dict)
    instruments: dict[str, int] = field(default_factory=dict)
    choices: dict[str, Choice] = field(default_factory=dict)
    # The fix chosen for each Sell left uncovered, by ``shortfall_key``
    corrections: dict[str, Fix] = field(default_factory=dict)
    # The Accounts whose proposed Deposits the user declined
    no_deposits: set[int] = field(default_factory=set)
    # The window: the path typed, and whether this import was applied
    path: str = ""
    done: bool = False

    def build(self) -> None:
        self.card = ui.card().classes("w-full max-w-4xl")
        with self.card:
            ui.label("Import z XTB i uzgadnianie").classes("text-xl font-bold")
            ui.label(
                "Zestawienia z xStation: okno poprowadzi Cię krok po kroku, od eksportu po uzgodnienie z transakcjami "
                "wpisanymi na kontach XTB. Domyślnie obowiązuje wersja XTB. Nic nie jest zapisywane przed „Zastosuj”."
            ).classes("text-sm")
            ui.button("Otwórz kreator importu XTB", icon="upload_file", on_click=self.open).props("no-caps").mark(
                "xtb-open"
            )
            # Opened from the card, which outlives it; each step in the order of STEPS
            bodies = (
                self._instructions,
                self._choose_files,
                self._matches,
                self._different,
                self._broker_only,
                self._mine_only,
                self._additions,
                self._review,
            )
            self.wizard = Wizard("xtb", [WizardStep(title, body) for title, body in zip(STEPS, bodies, strict=True)])

    def open(self) -> None:
        self.done = False
        self.wizard.open()

    def load(self, text: str) -> None:
        self.path = text
        try:
            self.statements = read_statements(FilePath(text.strip()))
        except TransactionError as error:
            ui.notify(str(error), type="negative")
            return
        self.reset_choices()
        self.wizard.go(3)

    def reset_choices(self) -> None:
        self.accounts = {}
        self.instruments = {}
        self.choices = {}
        self.corrections = {}
        self.no_deposits = set()
        self.done = False

    def reset(self) -> None:
        """Forget the statements and choices, e.g. after the data was cleared: they name removed ids."""
        self.statements = []
        self.reset_choices()
        self.wizard.close()

    def _decisions(self) -> XtbDecisions:
        return XtbDecisions(
            dict(self.accounts),
            dict(self.instruments),
            dict(self.choices),
            dict(self.corrections),
            frozenset(self.no_deposits),
        )

    def render(self) -> None:
        self.wizard.render()

    def _preview(self) -> XtbPreview:
        return preview_xtb(self.engine, self.statements, self.rates, self._decisions())

    def _names(self) -> dict[int, str]:
        return {account.id: account.name for account in list_accounts(self.engine)}

    def _describer(self) -> Describer:
        return Describer(self._names(), {i.id: i.name for i in list_instruments(self.engine)})

    @staticmethod
    def _matched(preview: XtbPreview) -> bool:
        if preview.unmatched_accounts or preview.unmatched_tickers:
            ui.label("Wróć do kroku 3 i dopasuj rachunki i tickery.").classes("k-muted")
            return False
        return True

    def _instructions(self) -> bool:
        ui.label("Zanim zaczniesz, przygotuj zestawienia:").classes("text-sm")
        for number, (title, text) in enumerate(INSTRUCTIONS, start=1):
            with ui.row().classes("w-full no-wrap gap-2"):
                ui.label(f"{number}.").classes("font-bold")
                with ui.column().classes("gap-0"):
                    ui.label(title).classes("font-bold")
                    ui.label(text).classes("text-sm")
        return True

    def _choose_files(self) -> bool:
        ui.label("Wskaż zestawienie XTB (.xlsx) albo folder z zestawieniami kilku rachunków.").classes("text-sm")
        path = ui.input("Plik albo folder z zestawieniami XTB", value=self.path).classes("w-full").mark("xtb-path")
        ui.button("Wczytaj", icon="visibility", on_click=lambda: self.load(path.value)).props("no-caps").mark(
            "xtb-load"
        )
        if self.statements:
            found = ", ".join(f"{s.account} ({s.product or 'bez operacji'})" for s in self.statements)
            ui.label(f"Wczytane rachunki: {found}.").classes("text-sm").mark("xtb-loaded")
        return bool(self.statements)

    def _matches(self) -> bool:
        preview = self._preview()
        ui.label(
            "Wybierz konto w aplikacji dla każdego rachunku XTB („Nie importuj”, by go pominąć) i instrument dla "
            "każdego tickera, którego aplikacja nie dopasowała sama. Wybory zostaną zapamiętane na następny import."
        ).classes("text-sm")
        self._accounts(preview, self._names())
        self._tickers(preview, {instrument.id: instrument.name for instrument in list_instruments(self.engine)})
        if preview.unmatched_accounts or preview.unmatched_tickers:
            ui.label("Dopasuj rachunki i tickery, aby przejść dalej.").classes("k-muted")
            return False
        self._problems(preview)
        return True

    def _different(self) -> bool:
        """The summary and the pairs that differ, with the entered Cash Transfers XTB shows as a Deposit or a
        Withdrawal, which always stay."""
        preview = self._preview()
        if not self._matched(preview):
            return False
        self._summary(preview)
        ui.label(
            "Te transakcje są i w XTB, i w aplikacji, ale różnią się datą, kwotą, ceną, prowizją albo podatkiem. "
            "„Weź XTB” (domyślnie) zastępuje Twój wpis wersją z XTB, z Twoim komentarzem; „Zostaw moje” zostawia go "
            "bez zmian."
        ).classes("text-sm")
        result, describe = preview.reconciliation, self._describer()
        different = result.different
        if not different:
            ui.label("Brak różnic.").classes("k-muted").mark("xtb-no-different")
        for pair in different:
            self._item(preview, pair, PAIR_OPTIONS, describe.pair(pair))
        linked = [pair for pair in result.pairs if pair.linked]
        if linked:
            ui.label(
                "Przelewy wpisane w aplikacji, które XTB pokazuje jako wpłatę albo wypłatę, zostają bez zmian: "
                "przesuwają też gotówkę na drugim koncie."
            ).classes("text-sm font-bold")
            for pair in linked:
                self._item(preview, pair, PAIR_OPTIONS, describe.pair(pair))
        same = [pair for pair in result.same if not pair.linked]
        if same:
            with ui.expansion(f"Zgodne ({len(same)})").classes("w-full").mark("xtb-same"):
                for pair in same:
                    ui.label(describe(pair.broker)).classes("text-sm")
        return True

    def _broker_only(self) -> bool:
        preview = self._preview()
        if not self._matched(preview):
            return False
        ui.label(
            "Te operacje są w XTB, a w aplikacji nie mają odpowiednika. „Dodaj” (domyślnie) zapisuje je; „Pomiń” ich "
            "nie dodaje i nie zaproponuje ponownie przy następnym imporcie."
        ).classes("text-sm")
        result, describe = preview.reconciliation, self._describer()
        if not result.broker_only:
            ui.label("Nic do dodania.").classes("k-muted").mark("xtb-no-broker-only")
        for draft in result.broker_only:
            self._item(preview, draft, BROKER_ONLY_OPTIONS, [describe(draft)])
        if preview.unsupported:
            with (
                ui.expansion(f"Nieobsługiwane operacje XTB, do wpisania ręcznie ({len(preview.unsupported)})")
                .classes("w-full")
                .mark("xtb-unsupported")
            ):
                for entry in preview.unsupported:
                    ui.label(f"{format_date(entry.day)}: {entry.note}").classes("text-sm")
        return True

    def _mine_only(self) -> bool:
        preview = self._preview()
        if not self._matched(preview):
            return False
        ui.label(
            "Te transakcje wpisałeś na kontach XTB w dniach objętych zestawieniem, a XTB ich nie ma. „Usuń” "
            "(domyślnie, bo zestawienie XTB jest źródłem prawdy) usuwa je; „Zostaw” zachowuje je jako Twój wpis. "
            "Koszty, splity i inne operacje, których zestawienie nie pokazuje, nie trafiają na tę listę."
        ).classes("text-sm")
        result, describe = preview.reconciliation, self._describer()
        if not result.mine_only:
            ui.label("Nic do usunięcia.").classes("k-muted").mark("xtb-no-mine-only")
        for transaction in result.mine_only:
            self._item(preview, transaction, MINE_ONLY_OPTIONS, [describe(transaction)])
        return True

    def _additions(self) -> bool:
        """The quantity corrections of the Sells the choices leave uncovered, and the Deposits proposed where they
        would take an Account's cash below zero, one checkbox per Account."""
        preview = self._preview()
        if not self._matched(preview):
            return False
        names = self._names()
        if preview.shortfalls:
            ui.label("Sprzedaże bez pokrycia (wybierz poprawkę albo wróć i wybierz inną wersję):").classes("font-bold")
            ui.label(HINT).classes("text-sm")
            correction_choices(preview.shortfalls, self._describer(), self._choose_correction, "xtb-corrections")
        ui.label(
            "Zestawienie od późniejszego dnia niż otwarcie rachunku nie ma wcześniejszych wpłat, a usunięte albo "
            "pominięte wpłaty też zabierają gotówkę; wtedy zakupy zdjęłyby gotówkę z konta poniżej zera. Aplikacja "
            "proponuje wpłaty w dniach, w których brakuje gotówki, dokładnie na brakującą kwotę. Na IKE i IKZE liczą "
            "się one do limitu wpłat roku swojej daty. Odznacz konto, jeśli wpłaty wpiszesz sam."
        ).classes("text-sm")
        if not preview.deposits:
            ui.label("Gotówka na kontach XTB nie spada poniżej zera: nic do uzupełnienia.").mark("xtb-no-deposits")
        deposit_choices(
            preview.deposits, names, lambda a: a not in self.no_deposits, self._keep_deposits, "xtb-deposits"
        )
        return True

    def _review(self) -> bool:
        preview = self._preview()
        if self.done:
            ui.label("Zapisano. Sprawdź jeszcze wskazówki poniżej.").classes("text-positive font-bold").mark("xtb-done")
        if not self._matched(preview):
            return False
        self._problems(preview)
        self._plan(preview)
        if deposits := preview.kept_deposits():
            ui.label(f"Uzupełnienia: {deposits_total(deposits)}.").mark("xtb-deposits-summary")
        if preview.shortfalls:
            ui.label(f"Poprawki ilości: {corrections_total(preview.shortfalls)}.").mark("xtb-corrections-summary")
        if any(shortfall.fix is None for shortfall in preview.shortfalls):
            ui.label("Wróć do kroku 7 i wybierz poprawkę dla każdej sprzedaży bez pokrycia.").classes(
                "text-negative"
            ).mark("xtb-corrections-missing")
        pending = len(preview.actions())
        apply = ui.button(f"Zastosuj ({pending})", icon="save", on_click=self.apply).props("no-caps")
        apply.mark("xtb-apply")
        if preview.blocked or pending == 0:
            apply.disable()
        with ui.expansion("Wskazówki do ręcznych poprawek", value=True).classes("w-full").mark("xtb-hints"):
            for hint in HINTS:
                ui.label(f"• {hint}").classes("text-sm")
        return True

    @staticmethod
    def _problems(preview: XtbPreview) -> None:
        """The entries that cannot become Transactions, e.g. without their NBP Rate; they block applying."""
        for problem in preview.problems:
            ui.label(f"{format_date(problem.entry.day)}: {problem.message}").classes("text-negative").mark(
                "xtb-problem"
            )

    @staticmethod
    def _plan(preview: XtbPreview) -> None:
        """How each category of the Reconciliation is resolved, before the corrections and Deposits."""
        result = preview.reconciliation

        def as_xtb(items: Sequence[Pair | TransactionDraft]) -> int:
            return sum(1 for item in items if preview.choice(item_key(item)) is Choice.BROKER)

        taken, added, deleted = as_xtb(result.different), as_xtb(result.broker_only), as_xtb(result.mine_only)
        ui.label(
            f"Różne: wersja XTB {taken}, Twoja {len(result.different) - taken}. "
            f"Tylko w XTB: dodane {added}, pominięte {len(result.broker_only) - added}. "
            f"Tylko w aplikacji: usunięte {deleted}, zostawione {len(result.mine_only) - deleted}."
        ).mark("xtb-plan")

    def _accounts(self, preview: XtbPreview, names: dict[int, str]) -> None:
        options: dict[int | str, str] = {NEW: "+ Nowe konto…", LEFT_OUT: "Nie importuj"}
        options.update(names.items())
        for statement in preview.statements:
            number = statement.account
            value: int | str | None = None
            if number in preview.accounts:
                chosen = preview.accounts[number]
                value = LEFT_OUT if chosen is None else chosen
            ui.select(
                options,
                value=value,
                label=f"Rachunek XTB {number} ({statement.product or 'bez operacji'}) to",
                on_change=lambda e, n=number, s=statement: self._choose_account(n, s, e.value),
            ).classes("w-full").mark(f"xtb-account-{number}")

    def _tickers(self, preview: XtbPreview, instruments: dict[int, str]) -> None:
        if not preview.unmatched_tickers:
            return
        ui.label("Tickery XTB bez instrumentu w aplikacji (wybierz istniejący albo utwórz nowy):").classes("font-bold")
        options: dict[int | str, str] = {NEW: "+ Nowy instrument…"}
        options.update(instruments.items())
        for ticker, name in preview.unmatched_tickers.items():
            ui.select(
                options,
                label=f"Ticker {ticker} ({name}) to",
                on_change=lambda e, t=ticker: self._choose_instrument(t, e.value),
            ).classes("w-full").mark(f"xtb-instrument-{ticker}")

    def _summary(self, preview: XtbPreview) -> None:
        result = preview.reconciliation
        linked = sum(1 for pair in result.pairs if pair.linked)
        ui.label(
            f"Zgodne: {len(result.same) - linked}, różne: {len(result.different)}, "
            f"tylko w XTB: {len(result.broker_only)}, tylko w aplikacji: {len(result.mine_only)}, "
            f"powiązane przelewy: {linked}, już uzgodnione: {preview.handled}, "
            f"nieobsługiwane: {len(preview.unsupported)}."
        ).mark("xtb-summary")
        ui.label(
            "„Wszędzie wersja XTB” i „Wszędzie moje” ustawiają wybór od razu w krokach 4–6; w każdym możesz go potem "
            "zmienić przy pojedynczej pozycji."
        ).classes("text-sm k-muted")
        with ui.row():
            ui.button("Wszędzie wersja XTB", on_click=lambda: self._all(preview, Choice.BROKER)).props(
                "outline no-caps"
            ).mark("xtb-all-broker")
            ui.button("Wszędzie moje", on_click=lambda: self._all(preview, Choice.MINE)).props("outline no-caps").mark(
                "xtb-all-mine"
            )

    def _item(
        self,
        preview: XtbPreview,
        item: Pair | TransactionDraft,
        options: dict[Choice, str],
        lines: list[str],
    ) -> None:
        key = item_key(item)
        with ui.row().classes("w-full items-center no-wrap border-b py-1").mark("xtb-item"):
            with ui.column().classes("gap-0 grow"):
                for line in lines:
                    ui.label(line).classes("text-sm")
            if isinstance(item, Pair) and item.linked:
                ui.label("Przelew wpisany w aplikacji zostaje").classes("text-sm k-muted")
                return
            ui.toggle(
                {choice.value: label for choice, label in options.items()},
                value=preview.choice(key).value,
                on_change=lambda e, k=key: self._choose(k, Choice(e.value)),
            ).props("no-caps dense").mark(f"xtb-choice-{key}")

    def _choose(self, key: str, choice: Choice) -> None:
        self.choices[key] = choice
        self.render()

    def _choose_correction(self, key: str, fix: Fix) -> None:
        self.corrections[key] = fix
        self.render()

    def _keep_deposits(self, account_id: int, keep: bool) -> None:
        if keep:
            self.no_deposits.discard(account_id)
        else:
            self.no_deposits.add(account_id)

    def _all(self, preview: XtbPreview, choice: Choice) -> None:
        result = preview.reconciliation
        items: list[Pair | TransactionDraft] = [*result.pairs, *result.broker_only, *result.mine_only]
        self.choices.update({item_key(item): choice for item in items})
        self.render()

    def _choose_account(self, number: str, statement: XtbStatement, choice: int | str | None) -> None:
        if choice is None:
            return
        if choice == NEW:
            with self.card:
                open_account_dialog(
                    self.engine,
                    None,
                    on_saved=lambda account: self._account_created(number, account),
                    name=f"XTB {statement.product}".strip(),
                )
            self.render()
            return
        self.accounts[number] = None if choice == LEFT_OUT else int(choice)
        self.render()

    def _account_created(self, number: str, account: Account) -> None:
        self.accounts[number] = account.id
        if self.on_account_added is not None:
            self.on_account_added()
        self.render()

    def _choose_instrument(self, ticker: str, choice: int | str | None) -> None:
        if choice is None:
            return
        if choice == NEW:
            with self.card:
                self.open_instrument(
                    None, query=yahoo_symbol(ticker) or ticker, on_saved=lambda i: self._instrument_created(ticker, i)
                )
            self.render()
            return
        self.instruments[ticker] = int(choice)
        self.render()

    def _instrument_created(self, ticker: str, instrument: Instrument) -> None:
        self.instruments[ticker] = instrument.id
        self.render()

    def apply(self) -> None:
        try:
            applied = checked_save(
                self.engine,
                lambda: apply_xtb(self.engine, self.statements, self.rates, self._decisions(), self.today()),
            )
        except TransactionError as error:
            ui.notify(str(error), type="negative")
            self.render()
            return
        count = format_count(len(applied.value.actions()), "pozycję", "pozycje", "pozycji")
        ui.notify(f"Uzgodniono z XTB {count}.", type="positive")
        show_warnings(applied.warnings, engine=self.engine, on_saved=self.on_saved)
        self.reset_choices()
        if self.on_saved is not None:
            self.on_saved()
        self.done = True
        self.render()


@dataclass(frozen=True)
class Describer:
    accounts: dict[int, str]
    instruments: dict[int, str]

    def __call__(self, draft: TransactionDraft) -> str:
        parts = [format_date(draft.date), self.accounts.get(draft.account_id, "?"), draft.transaction_type.label]
        if draft.target_account_id is not None:
            parts[1] += f" → {self.accounts.get(draft.target_account_id, '?')}"
        if draft.instrument_id is not None:
            parts.append(self.instruments.get(draft.instrument_id, "?"))
        if draft.quantity is not None:
            parts.append(format_quantity(draft.quantity))
        parts.append(format_pln(draft.actual_amount))
        if draft.comment:
            parts.append(draft.comment)
        return " · ".join(parts)

    def pair(self, pair: Pair) -> list[str]:
        return [f"Wpisana: {self(pair.mine)}", f"XTB: {self(pair.broker)}"]
