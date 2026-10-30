"""Ustawienia > Limity i reguły > Transakcje cykliczne: the first Recurring Rule's step-by-step window (#275).

Offered while there is no rule: the user picks an example (``domain/rule_examples.py``) or "Własna", fills in the
Account(s), amount, day and first occurrence the example pre-fills, sees the next Drafts the rule will bring and saves
it as the rule dialog would. A closing note says where the Drafts appear and how to confirm or skip them.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.accounts import Account
from financial_app.domain.formatting import format_amount, format_date, format_exact
from financial_app.domain.recurring import (
    Frequency,
    RecurringRuleDraft,
    RecurringRuleError,
    check_buy,
    first_occurrence_after,
    parse_rule_fields,
    upcoming_occurrences,
)
from financial_app.domain.rule_examples import CUSTOM, RULE_EXAMPLES, RuleExample, example_defaults
from financial_app.domain.transactions import PLN, TransactionType
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.recurring_rules import add_rule
from financial_app.ui.recurring_rules import TYPE_OPTIONS, instrument_labels
from financial_app.ui.wizard import Wizard, WizardStep

EXAMPLES = {example.key: example for example in (*RULE_EXAMPLES, CUSTOM)}
# How many of the rule's Drafts the preview lists
PREVIEW_COUNT = 3
DRAFTS_NOTE = (
    "Szkic pojawia się nad listą w zakładce Transakcje w dniu terminu, a liczba szkiców czeka przy dzwonku w nagłówku. "
    "Przy każdym możesz: zatwierdzić go (✓), edytować przed zapisem (kupno: wpisujesz liczbę i cenę jednostek) albo "
    "pominąć ten termin. Transakcja wpisana ręcznie do 7 dni od terminu zastępuje szkic. Regułę wyłączysz, "
    "zmienisz albo usuniesz tutaj, w Transakcjach cyklicznych."
)


def _currency(account: Account) -> str:
    """The rule's currency: PLN when the Account holds it (or nothing), else its first Cash Currency."""
    held = account.cash_currencies
    return PLN if PLN in held or not held else held[0]


@dataclass
class FirstRuleWizard:
    """The window and the rule it is filling in; ``on_saved`` runs after the rule is saved."""

    engine: Engine
    today: Callable[[], date]
    on_saved: Callable[[], object] | None = None
    example: str = RULE_EXAMPLES[0].key
    name: str = ""
    account_id: int | None = None
    target_id: int | None = None
    instrument_id: int | None = None
    transaction_type: TransactionType = TransactionType.DEPOSIT
    amount: str = ""
    day: str = ""
    start: str = ""
    # The first occurrence last proposed, which a change of the day replaces while the user has not typed another
    proposed_start: str = ""
    # The rule once saved: step 3 then shows it, not the fields changed after
    saved: RecurringRuleDraft | None = None
    accounts: dict[int, Account] = field(default_factory=dict)
    wizard: Wizard | None = None
    start_field: ui.input | None = None

    def open(self) -> None:
        if self.wizard is None:
            steps = (
                WizardStep("Wybierz przykład", self._choose_example),
                WizardStep("Uzupełnij regułę", self._details),
                WizardStep("Podgląd i zapis", self._review),
            )
            # On the page itself: Ustawienia draws only the chosen section, and the rule list it is opened from
            # redraws once the rule is saved
            with ui.context.client.content:
                self.wizard = Wizard("first-rule", steps, width="w-[40rem]")
        self.saved = None
        self._prefill(EXAMPLES[self.example])
        self.wizard.open()

    def _render(self) -> None:
        assert self.wizard is not None
        self.wizard.render()

    def _prefill(self, example: RuleExample) -> None:
        self.example = example.key
        self.accounts = {account.id: account for account in list_accounts(self.engine) if account.active}
        defaults = example_defaults(example, self.today(), list(self.accounts.values()))
        self.name = example.name
        self.account_id = defaults.account_id
        self.target_id = defaults.target_account_id
        self.instrument_id = None
        self.transaction_type = defaults.transaction_type
        self.amount = "" if defaults.amount is None else format_exact(defaults.amount)
        self.day = str(defaults.day_of_month)
        self.start = self.proposed_start = format_date(defaults.start_date)

    def _day(self, text: str | None) -> None:
        """Keep the day typed; the first occurrence follows it, as in the rule dialog, until the user types one."""
        self.day = text or ""
        try:
            day_of_month = int(self.day.strip())
        except ValueError:
            return
        if 1 <= day_of_month <= 31 and self.start == self.proposed_start:
            due = first_occurrence_after(day_of_month, Frequency.MONTHLY, self.today())
            self.start = self.proposed_start = format_date(due)
            # In place, so the day field keeps the focus
            if self.start_field is not None:
                self.start_field.value = self.start

    def _choose(self, key: str | None) -> None:
        if key is not None and key != self.example:
            self._prefill(EXAMPLES[key])
            self._render()

    def _choose_example(self) -> bool:
        if not self.accounts:
            ui.label("Najpierw dodaj konto w sekcji Konta.").classes("k-muted")
            return False
        ui.label(
            "Reguła cykliczna co jakiś czas proponuje transakcję do zatwierdzenia, np. comiesięczną wpłatę. Zacznij od "
            "przykładu: wszystkie pola zmienisz w następnym kroku."
        ).classes("text-sm")
        ui.radio(
            {key: example.label for key, example in EXAMPLES.items()},
            value=self.example,
            on_change=lambda e: self._choose(e.value),
        ).mark("first-rule-example")
        ui.label(EXAMPLES[self.example].description).classes("text-sm k-muted").mark("first-rule-description")
        return True

    def _details(self) -> bool:
        names = {account.id: account.name for account in self.accounts.values()}
        ui.input("Nazwa", value=self.name, on_change=lambda e: setattr(self, "name", e.value)).classes("w-full").mark(
            "first-rule-name"
        )
        if self.example == CUSTOM.key:
            ui.select(
                TYPE_OPTIONS, label="Typ", value=self.transaction_type.value, on_change=lambda e: self._type(e.value)
            ).classes("w-full").mark("first-rule-type")
        ui.select(names, label="Konto", value=self.account_id, on_change=lambda e: self._account(e.value)).classes(
            "w-full"
        ).mark("first-rule-account")
        if self.transaction_type is TransactionType.CASH_TRANSFER:
            others = {key: label for key, label in names.items() if key != self.account_id}
            ui.select(
                others,
                label="Konto docelowe",
                value=self.target_id if self.target_id in others else None,
                on_change=lambda e: setattr(self, "target_id", e.value),
            ).classes("w-full").mark("first-rule-target")
        if self.transaction_type is TransactionType.BUY:
            ui.select(
                instrument_labels(self.engine),
                label="Instrument",
                value=self.instrument_id,
                with_input=True,
                on_change=lambda e: setattr(self, "instrument_id", e.value),
            ).classes("w-full").mark("first-rule-instrument")
        label = "Planowana kwota" if self.transaction_type is TransactionType.BUY else "Kwota"
        if self.account_id is not None:
            label += f" ({_currency(self.accounts[self.account_id])})"
        ui.input(label, value=self.amount, on_change=lambda e: setattr(self, "amount", e.value)).classes("w-full").mark(
            "first-rule-amount"
        )
        day = ui.input("Dzień miesiąca", value=self.day, on_change=lambda e: self._day(e.value))
        day.classes("w-full").mark("first-rule-day")
        day.props('hint="Od 1 do 31; weekend przesuwa termin na poniedziałek"')
        first = ui.input("Pierwszy termin", value=self.start, on_change=lambda e: setattr(self, "start", e.value))
        first.classes("w-full").mark("first-rule-start")
        self.start_field = first
        first.props('hint="dd.mm.rrrr; reguła powtarza się co miesiąc od tego terminu"')
        return True

    def _type(self, value: str | None) -> None:
        if value is not None:
            self.transaction_type = TransactionType(value)
            self._render()

    def _account(self, account_id: int | None) -> None:
        self.account_id = account_id
        self._render()

    def _draft(self) -> RecurringRuleDraft:
        """The rule as filled in, checked as the rule dialog checks it."""
        if self.account_id is None:
            raise RecurringRuleError("Wybierz konto.")
        amount, day, start, _ = parse_rule_fields(self.amount, self.day, self.start)
        buying = self.transaction_type is TransactionType.BUY
        if buying and self.instrument_id is not None:
            instrument = next(i for i in list_instruments(self.engine) if i.id == self.instrument_id)
            check_buy(self.accounts[self.account_id], instrument)
        transfer = self.transaction_type is TransactionType.CASH_TRANSFER
        return RecurringRuleDraft(
            name=self.name,
            account_id=self.account_id,
            transaction_type=self.transaction_type,
            amount=amount,
            currency=_currency(self.accounts[self.account_id]),
            frequency=Frequency.MONTHLY,
            day_of_month=day,
            start_date=start,
            instrument_id=self.instrument_id if buying else None,
            target_account_id=self.target_id if transfer else None,
        )

    def _review(self) -> bool:
        """The rule and its next Drafts; once saved, the saved rule, whatever the fields were changed to since."""
        if self.saved is not None:
            ui.label("Zapisano regułę.").classes("text-positive font-bold").mark("first-rule-done")
        try:
            draft = self.saved or self._draft()
        except RecurringRuleError as error:
            ui.label(str(error)).classes("text-negative").mark("first-rule-error")
            ui.label("Wróć do kroku 2 i popraw regułę.").classes("k-muted")
            ui.button("Zapisz regułę", icon="save").props("no-caps").mark("first-rule-save").disable()
            return False
        what = [self.accounts[draft.account_id].name]
        if draft.target_account_id is not None:
            what = [f"{what[0]} → {self.accounts[draft.target_account_id].name}"]
        if draft.instrument_id is not None:
            what.append(instrument_labels(self.engine)[draft.instrument_id])
        what.append(format_amount(draft.amount, draft.currency))
        ui.label(f"{draft.name}: {draft.transaction_type.label}, {Frequency.MONTHLY.label}").classes("font-bold")
        ui.label(" · ".join(what)).classes("text-sm").mark("first-rule-summary")
        ui.label("Najbliższe szkice:").classes("font-medium mt-2")
        for due in upcoming_occurrences(draft, PREVIEW_COUNT):
            ui.label(f"{format_date(due)}: {draft.transaction_type.label}").classes("text-sm").mark("first-rule-draft")
        saved = self.saved is not None
        if not saved:
            ui.button("Zapisz regułę", icon="save", on_click=lambda: self._save(draft)).props("no-caps").mark(
                "first-rule-save"
            )
        with ui.expansion("Gdzie pojawią się szkice?", value=saved).classes("w-full").mark("first-rule-drafts-note"):
            ui.label(DRAFTS_NOTE).classes("text-sm")
        return True

    def _save(self, draft: RecurringRuleDraft) -> None:
        try:
            add_rule(self.engine, draft)
        except RecurringRuleError as error:
            ui.notify(str(error), type="negative")
            return
        self.saved = draft
        self._render()
        if self.on_saved is not None:
            self.on_saved()
