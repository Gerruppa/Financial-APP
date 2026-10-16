"""Ustawienia > Import z XTB: XTB statements reconciled with the Transactions entered (spec 7, L-17).

The user points at the exported files, matches each XTB account to an Account and each ticker to an Instrument, then
resolves every difference: XTB's version by default, as XTB is the source of truth for its Accounts, or their own.
Nothing is saved until "Zastosuj".
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path as FilePath

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.accounts import Account
from financial_app.domain.formatting import format_count, format_date, format_pln, format_quantity
from financial_app.domain.instruments import Instrument
from financial_app.domain.reconciliation import Choice, Pair, item_key
from financial_app.domain.transactions import TransactionDraft, TransactionError
from financial_app.domain.xtb_import import XtbStatement, yahoo_symbol
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.sources.spreadsheet import NbpLookup
from financial_app.sources.xtb import LEFT_OUT, XtbDecisions, XtbPreview, apply_xtb, preview_xtb, read_statements
from financial_app.ui.accounts import open_account_dialog

NEW = "new"
PAIR_OPTIONS = {Choice.BROKER: "Weź XTB", Choice.MINE: "Zostaw moje"}
BROKER_ONLY_OPTIONS = {Choice.BROKER: "Dodaj", Choice.MINE: "Pomiń"}
MINE_ONLY_OPTIONS = {Choice.BROKER: "Usuń", Choice.MINE: "Zostaw"}

OpenInstrument = Callable[..., None]


@dataclass
class XtbImportSection:
    """Reads the statements, lets the user match and resolve, and applies on approval.

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

    def build(self) -> None:
        self.card = ui.card().classes("w-full max-w-4xl")
        with self.card:
            ui.label("Import z XTB i uzgadnianie").classes("text-xl font-bold")
            ui.label(
                "Wskaż zestawienie z xStation (Historia konta → eksport .xlsx) albo folder z zestawieniami kilku "
                "rachunków. Transakcje z XTB są porównywane z wpisanymi na tych kontach; domyślnie obowiązuje wersja "
                "XTB. Nic nie jest zapisywane przed „Zastosuj”."
            ).classes("text-sm")
            path = ui.input("Plik albo folder z zestawieniami XTB").classes("w-full").mark("xtb-path")
            ui.button("Wczytaj", icon="visibility", on_click=lambda: self.load(path.value)).props("no-caps").mark(
                "xtb-load"
            )
            self.result = ui.column().classes("w-full gap-2").mark("xtb-result")

    def load(self, text: str) -> None:
        try:
            self.statements = read_statements(FilePath(text.strip()))
        except TransactionError as error:
            self.result.clear()
            ui.notify(str(error), type="negative")
            return
        self.reset_choices()
        self.render()

    def reset_choices(self) -> None:
        self.accounts = {}
        self.instruments = {}
        self.choices = {}

    def reset(self) -> None:
        """Forget the statements and choices, e.g. after the data was cleared: they name removed ids."""
        self.statements = []
        self.reset_choices()
        self.result.clear()

    def _decisions(self) -> XtbDecisions:
        return XtbDecisions(dict(self.accounts), dict(self.instruments), dict(self.choices))

    def render(self) -> None:
        preview = preview_xtb(self.engine, self.statements, self.rates, self._decisions())
        names = {account.id: account.name for account in list_accounts(self.engine)}
        instruments = {instrument.id: instrument.name for instrument in list_instruments(self.engine)}
        self.result.clear()
        with self.result:
            self._accounts(preview, names)
            self._tickers(preview, instruments)
            if preview.unmatched_accounts or preview.unmatched_tickers:
                ui.label("Dopasuj rachunki i tickery, aby zobaczyć porównanie.").classes("text-gray-500")
                return
            describe = _Describer(names, instruments)
            for problem in preview.problems:
                ui.label(f"{format_date(problem.entry.day)}: {problem.message}").classes("text-negative").mark(
                    "xtb-problem"
                )
            self._summary(preview)
            self._lists(preview, describe)
            pending = len(preview.actions())
            apply = ui.button(f"Zastosuj ({pending})", icon="save", on_click=self.apply).props("no-caps")
            apply.mark("xtb-apply")
            if preview.blocked or pending == 0:
                apply.disable()

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
        ui.label(
            f"Zgodne: {len(result.same)}, różne: {len(result.different)}, tylko w XTB: {len(result.broker_only)}, "
            f"tylko w aplikacji: {len(result.mine_only)}, już uzgodnione: {preview.handled}, "
            f"nieobsługiwane: {len(preview.unsupported)}."
        ).mark("xtb-summary")
        with ui.row():
            ui.button("Wszędzie wersja XTB", on_click=lambda: self._all(preview, Choice.BROKER)).props(
                "outline no-caps"
            ).mark("xtb-all-broker")
            ui.button("Wszędzie moje", on_click=lambda: self._all(preview, Choice.MINE)).props("outline no-caps").mark(
                "xtb-all-mine"
            )

    def _lists(self, preview: XtbPreview, describe: _Describer) -> None:
        result = preview.reconciliation
        if result.different:
            ui.label("Różnią się (u góry wpisana, pod nią XTB):").classes("font-bold")
        for pair in result.different:
            self._item(preview, pair, PAIR_OPTIONS, describe.pair(pair))
        if result.broker_only:
            ui.label("Tylko w XTB:").classes("font-bold")
        for draft in result.broker_only:
            self._item(preview, draft, BROKER_ONLY_OPTIONS, [describe(draft)])
        if result.mine_only:
            ui.label("Tylko w aplikacji (XTB ich nie ma):").classes("font-bold")
        for transaction in result.mine_only:
            self._item(preview, transaction, MINE_ONLY_OPTIONS, [describe(transaction)])
        if result.same:
            with ui.expansion(f"Zgodne ({len(result.same)})").classes("w-full").mark("xtb-same"):
                for pair in result.same:
                    ui.label(describe(pair.broker)).classes("text-sm")
        if preview.unsupported:
            with (
                ui.expansion(f"Nieobsługiwane operacje XTB, do wpisania ręcznie ({len(preview.unsupported)})")
                .classes("w-full")
                .mark("xtb-unsupported")
            ):
                for entry in preview.unsupported:
                    ui.label(f"{format_date(entry.day)}: {entry.note}").classes("text-sm")

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
                ui.label("Przelew wpisany w aplikacji zostaje").classes("text-sm text-gray-500")
                return
            ui.toggle(
                {choice.value: label for choice, label in options.items()},
                value=preview.choice(key).value,
                on_change=lambda e, k=key: self._choose(k, Choice(e.value)),
            ).props("no-caps dense").mark(f"xtb-choice-{key}")

    def _choose(self, key: str, choice: Choice) -> None:
        self.choices[key] = choice
        self.render()

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
            applied = apply_xtb(self.engine, self.statements, self.rates, self._decisions(), self.today())
        except TransactionError as error:
            ui.notify(str(error), type="negative")
            self.render()
            return
        count = format_count(len(applied.actions()), "pozycję", "pozycje", "pozycji")
        ui.notify(f"Uzgodniono z XTB {count}.", type="positive")
        self.choices = {}
        if self.on_saved is not None:
            self.on_saved()
        self.render()


@dataclass(frozen=True)
class _Describer:
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
