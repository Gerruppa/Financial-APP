"""Ustawienia > Transakcje cykliczne (issue #97, spec 3.3.1 point 9): the Recurring Rules with their next occurrence,
and the rule dialog, which also lists the skipped occurrences ("Przywróć") and skips the overdue ones."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.bonds import bond_type_of
from financial_app.domain.formatting import format_amount, format_count, format_date, format_exact
from financial_app.domain.recurring import (
    RECURRING_TYPES,
    Frequency,
    RecurringRule,
    RecurringRuleDraft,
    RecurringRuleError,
    RuleDefaults,
    check_buy,
    first_occurrence_after,
    new_rule_defaults,
    next_occurrence,
    parse_rule_fields,
)
from financial_app.domain.transactions import PLN, TransactionType
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.recurring_rules import (
    add_rule,
    delete_rule,
    list_rules,
    restore_occurrence,
    set_rule_active,
    skip_overdue,
    skipped_occurrences,
    update_rule,
)
from financial_app.ui.dialogs import movable_dialog

TYPE_OPTIONS = {kind.value: kind.label for kind in RECURRING_TYPES}
FREQUENCY_OPTIONS = {frequency.value: frequency.label for frequency in Frequency}


def instrument_labels(engine: Engine) -> dict[int, str]:
    """Each Instrument's name as a rule shows it: a Bond Series by its bond type, as a rule buys whichever month's
    Series of it (#149)."""
    return {
        instrument.id: str(bond_type_of(instrument.name)) if instrument.is_bond_series else instrument.name
        for instrument in list_instruments(engine)
    }


def accounts_of(rule: RecurringRule, accounts: dict[int, str]) -> str:
    """The rule's Account, and a Cash Transfer's target after an arrow."""
    if rule.target_account_id is None:
        return accounts[rule.account_id]
    return f"{accounts[rule.account_id]} → {accounts[rule.target_account_id]}"


@dataclass
class RecurringRulesSection:
    """The Transakcje cykliczne card; ``on_changed`` runs after a rule is saved, switched, deleted or its skips
    change, so the Drafts redraw. ``open_first_rule`` opens the first rule's window (``ui/first_rule.py``), offered
    while there is no rule."""

    engine: Engine
    today: Callable[[], date]
    on_changed: Callable[[], object] | None = None
    open_first_rule: Callable[[], object] | None = None

    def build(self) -> None:
        with ui.card().classes("w-full max-w-4xl"):
            with ui.row().classes("w-full items-center"):
                ui.label("Transakcje cykliczne").classes("text-xl font-bold")
                ui.space()
                ui.button("Dodaj regułę", icon="add", on_click=lambda: self.open_dialog(None)).props("no-caps").mark(
                    "add-recurring-rule"
                )
            ui.label(
                "Terminy, które minęły bez pasującej transakcji, czekają w zakładce Transakcje na zatwierdzenie."
            ).classes("text-sm k-muted")
            # The marker sits outside the refreshable list so it survives a refresh
            with ui.column().classes("w-full gap-1").mark("recurring-rules"):
                self.rule_list()

    def refresh(self) -> None:
        self.rule_list.refresh()

    @ui.refreshable_method
    def rule_list(self) -> None:
        rules = list_rules(self.engine)
        if not rules:
            ui.label("Nie dodano jeszcze żadnej reguły.").classes("k-muted")
            if self.open_first_rule is not None:
                ui.button("Pierwsza reguła krok po kroku", icon="auto_fix_high", on_click=self.open_first_rule).props(
                    "outline no-caps"
                ).mark("first-rule-open")
            return
        accounts = {account.id: account.name for account in list_accounts(self.engine)}
        instruments = instrument_labels(self.engine)
        for rule in rules:
            self._rule_row(rule, accounts, instruments)

    def _rule_row(self, rule: RecurringRule, accounts: dict[int, str], instruments: dict[int, str]) -> None:
        with ui.row().classes("w-full items-center no-wrap border-b py-1").mark("recurring-rule"):
            with ui.column().classes("gap-0 grow" + ("" if rule.active else " opacity-60")):
                with ui.row().classes("items-center gap-2"):
                    ui.label(rule.name).classes("font-medium")
                    ui.badge(rule.transaction_type.label).props("outline")
                    if not rule.active:
                        ui.badge("wyłączona", color="grey")
                what = [accounts_of(rule, accounts)]
                if rule.instrument_id is not None:
                    what.append(instruments[rule.instrument_id])
                what.append(format_amount(rule.amount, rule.currency))
                ui.label(" · ".join(what)).classes("text-sm k-muted")
                when = [f"{rule.frequency.label}, dzień {rule.day_of_month}"]
                upcoming = next_occurrence(rule, self.today())
                when.append("bez kolejnych terminów" if upcoming is None else f"najbliższy {format_date(upcoming)}")
                ui.label(" · ".join(when)).classes("text-sm k-muted")
            ui.button(icon="toggle_on" if rule.active else "toggle_off", on_click=lambda: self._switch(rule)).props(
                f'flat round aria-label="{"Wyłącz" if rule.active else "Włącz"} {rule.name}"'
            ).mark("toggle-recurring-rule")
            ui.button(icon="edit", on_click=lambda: self.open_dialog(rule)).props(
                f'flat round aria-label="Edytuj {rule.name}"'
            ).mark("edit-recurring-rule")
            ui.button(icon="delete", on_click=lambda: self._confirm_delete(rule)).props(
                f'flat round color=negative aria-label="Usuń {rule.name}"'
            ).mark("delete-recurring-rule")

    def open_dialog(self, rule: RecurringRule | None) -> None:
        open_rule_dialog(self.engine, self.today(), self.changed, rule)

    def _switch(self, rule: RecurringRule) -> None:
        set_rule_active(self.engine, rule.id, not rule.active)
        self.changed()

    def _confirm_delete(self, rule: RecurringRule) -> None:
        confirmation = ui.dialog()
        confirmation.on("hide", confirmation.delete)

        def delete() -> None:
            confirmation.close()
            delete_rule(self.engine, rule.id)
            self.changed()

        with confirmation, ui.card():
            ui.label(f"Usunąć regułę „{rule.name}”?").classes("text-lg font-bold")
            ui.label("Zapisane z niej transakcje zostaną.").classes("k-muted")
            with ui.row().classes("w-full justify-end"):
                ui.button("Anuluj", on_click=confirmation.close).props("flat")
                ui.button("Usuń", on_click=delete).props("color=negative").mark("confirm-delete-recurring-rule")
        confirmation.open()

    def changed(self) -> None:
        """Redraw the list and let the Drafts redraw: a rule was added, changed or removed."""
        self.rule_list.refresh()
        if self.on_changed is not None:
            self.on_changed()


def open_rule_dialog(
    engine: Engine,
    today: date,
    on_saved: Callable[[], object],
    rule: RecurringRule | None = None,
    defaults: RuleDefaults | None = None,
) -> None:
    """Open the rule form: a new rule (``rule`` ``None``) opening with ``defaults`` (by default a monthly Deposit
    from its next occurrence), or ``rule`` to edit, with its skipped occurrences. ``on_saved`` runs after a save and
    after its skips change."""
    accounts = {account.id: account for account in list_accounts(engine) if account.active or rule is not None}
    if rule is not None:
        start = RuleDefaults(
            rule.account_id,
            rule.transaction_type,
            rule.day_of_month,
            rule.start_date,
            rule.amount,
            rule.currency,
            rule.instrument_id,
            rule.frequency,
            rule.target_account_id,
        )
    else:
        start = defaults or new_rule_defaults(today, next(iter(accounts), None))
    # On the page itself: the list it was opened from redraws when its skips change, and "Powtarzaj…" closes the
    # transaction dialog it comes from
    with ui.context.client.content:
        dialog = movable_dialog()
    dialog.on("hide", dialog.delete)
    with dialog, ui.card().classes("w-[480px]"):
        ui.label("Nowa reguła cykliczna" if rule is None else "Edytuj regułę cykliczną").classes("text-lg font-bold")
        if not accounts:
            ui.label("Najpierw dodaj konto w sekcji Konta.").classes("k-muted")
            with ui.row().classes("w-full justify-end"):
                ui.button("Zamknij", on_click=dialog.close).props("flat")
            dialog.open()
            return
        name = ui.input("Nazwa", value=rule.name if rule else "").classes("w-full").mark("rule-name")
        name.props('hint="Widoczna na szkicu, np. „Wpłata IKE”"')
        account_id = start.account_id if start.account_id in accounts else next(iter(accounts))
        account = ui.select({a.id: a.name for a in accounts.values()}, label="Konto", value=account_id)
        account.classes("w-full k-field").props("filled").mark("rule-account")
        kind = ui.select(TYPE_OPTIONS, label="Typ", value=start.transaction_type.value).classes("w-full")
        kind.mark("rule-type")
        target = ui.select({}, label="Konto docelowe", value=None).classes("w-full").mark("rule-target")
        saved_instruments = {i.id: i for i in list_instruments(engine)}
        instruments = {i.id: i.name for i in saved_instruments.values()}
        instrument = ui.select(instruments, label="Instrument", value=start.instrument_id, with_input=True)
        instrument.classes("w-full").mark("rule-instrument")
        amount = ui.input(value="" if start.amount is None else format_exact(start.amount)).classes("w-full")
        amount.mark("rule-amount")
        currency = ui.select([start.currency], label="Waluta", value=start.currency).classes("w-full")
        currency.mark("rule-currency")
        frequency = ui.select(FREQUENCY_OPTIONS, label="Częstotliwość", value=start.frequency.value)
        frequency.classes("w-full").mark("rule-frequency")
        day = ui.input("Dzień miesiąca", value=str(start.day_of_month)).classes("w-full").mark("rule-day")
        day.props('hint="Od 1 do 31; po końcu miesiąca jego ostatni dzień, weekend przesuwa na poniedziałek"')
        first = ui.input("Pierwszy termin", value=format_date(start.start_date)).classes("w-full").mark("rule-start")
        first.props('hint="dd.mm.rrrr; jego miesiąc wyznacza miesiące kolejnych terminów"')
        end = ui.input(
            "Ostatni termin (opcjonalnie)", value=format_date(rule.end_date) if rule and rule.end_date else ""
        )
        end.classes("w-full").mark("rule-end")
        active = ui.switch("Aktywna", value=rule.active if rule else True).mark("rule-active")
        error = ui.label().classes("text-negative").mark("rule-error")

        targets = {a.id: a.name for a in list_accounts(engine) if a.active or a.id == start.target_account_id}

        def show() -> None:
            buying = kind.value == TransactionType.BUY.value
            instrument.visible = buying
            # A Cash Transfer goes to another Account than its own
            target.visible = kind.value == TransactionType.CASH_TRANSFER.value
            others = {key: label for key, label in targets.items() if key != account.value}
            chosen = target.value if target.value is not None else start.target_account_id
            target.set_options(others, value=chosen if chosen in others else None)
            amount.props(f'label="{"Planowana kwota" if buying else "Kwota"}"')
            held = accounts[account.value].cash_currencies
            options = list(held) or [PLN]
            currency.set_options(options, value=currency.value if currency.value in options else options[0])

        show()
        for field in (kind, account):
            field.on_value_change(show)

        # A new rule's start follows its day and frequency to their next occurrence, until the user types a start
        proposed = [first.value]

        def propose_start() -> None:
            if rule is not None or defaults is not None or first.value != proposed[0]:
                return
            try:
                day_of_month = int((day.value or "").strip())
            except ValueError:
                return
            if 1 <= day_of_month <= 31:
                first.value = proposed[0] = format_date(
                    first_occurrence_after(day_of_month, Frequency(frequency.value), today)
                )

        day.on_value_change(propose_start)
        frequency.on_value_change(propose_start)

        def draft() -> RecurringRuleDraft:
            parsed_amount, parsed_day, parsed_start, parsed_end = parse_rule_fields(
                amount.value or "", day.value or "", first.value or "", end.value or ""
            )
            buying = kind.value == TransactionType.BUY.value
            if buying and instrument.value in saved_instruments:
                check_buy(accounts[account.value], saved_instruments[instrument.value])
            return RecurringRuleDraft(
                name=name.value or "",
                account_id=account.value,
                transaction_type=TransactionType(kind.value),
                amount=parsed_amount,
                currency=currency.value,
                frequency=Frequency(frequency.value),
                day_of_month=parsed_day,
                start_date=parsed_start,
                end_date=parsed_end,
                instrument_id=instrument.value if buying else None,
                active=bool(active.value),
                target_account_id=target.value if kind.value == TransactionType.CASH_TRANSFER.value else None,
            )

        def save() -> None:
            try:
                if rule is None:
                    add_rule(engine, draft())
                else:
                    update_rule(engine, rule.id, draft())
            except RecurringRuleError as exc:
                error.text = str(exc)
                return
            dialog.close()
            on_saved()

        if rule is not None:
            _skips(engine, rule, today, on_saved)

        with ui.row().classes("w-full items-center"):
            ui.space()
            ui.button("Anuluj", on_click=dialog.close).props("flat")
            ui.button("Zapisz", on_click=save).mark("save-rule")
    dialog.open()


def _skips(engine: Engine, rule: RecurringRule, today: date, on_changed: Callable[[], object]) -> None:
    """The rule's skipped occurrences, each with "Przywróć", and "Pomiń zaległe"."""

    @ui.refreshable
    def skips() -> None:
        skipped = skipped_occurrences(engine, rule.id)
        ui.label("Pominięte terminy").classes("font-medium mt-2")
        if not skipped:
            ui.label("Brak pominiętych terminów.").classes("text-sm k-muted")
        for day in skipped:
            with ui.row().classes("w-full items-center border-b").mark("rule-skip"):
                ui.label(format_date(day)).classes("grow")
                ui.button("Przywróć", on_click=lambda day=day: restore(day)).props("flat dense no-caps").mark(
                    "restore-skip"
                )

    def restore(day: date) -> None:
        restore_occurrence(engine, rule.id, day)
        skips.refresh()
        on_changed()

    def skip_all() -> None:
        count = skip_overdue(engine, rule.id, today)
        ui.notify(f"Pominięto {format_count(count, 'termin', 'terminy', 'terminów')}.", type="positive")
        skips.refresh()
        on_changed()

    skips()
    ui.button("Pomiń zaległe", on_click=skip_all).props("flat no-caps").mark("skip-overdue").tooltip(
        "Pomija wszystkie niezatwierdzone terminy sprzed dziś"
    )
