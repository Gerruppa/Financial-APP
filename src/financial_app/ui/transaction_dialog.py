"""The transaction dialog for adding, editing and deleting a Transaction (spec 3.3).

It binds its widgets to the form model in ``domain/transaction_form.py`` (#111), which holds what each
Transaction Type shows and how its fields read, and saves through ``sources/transaction_saving.py`` (#110).
"""

from collections.abc import Callable, Mapping
from datetime import date

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.bonds import BondType
from financial_app.domain.currencies import MissingNbpRateError
from financial_app.domain.formatting import (
    format_exact,
)
from financial_app.domain.instruments import InstrumentError
from financial_app.domain.recurring import RECURRING_TYPES, repeating
from financial_app.domain.transaction_form import (
    BOND_TYPE_OPTIONS,
    BUY_CURRENCY,
    SELL_CURRENCY,
    TRANSACTION_TYPE_OPTIONS,
    FormContext,
    FormLayout,
    FormPrefill,
    FormState,
    FormTexts,
    TransactionForm,
)
from financial_app.domain.transactions import (
    Transaction,
    TransactionDraft,
    TransactionError,
    TransactionType,
)
from financial_app.persistence.accounts import list_accounts
from financial_app.persistence.bond_data import load_series_terms
from financial_app.persistence.bond_series import list_bond_series, load_bond_data
from financial_app.persistence.instruments import list_instruments
from financial_app.persistence.transactions import transactions_in_entry_order
from financial_app.sources.nbp import NbpRates
from financial_app.sources.transaction_saving import delete_saved, restore_saved, save_transaction
from financial_app.ui.dialogs import movable_dialog
from financial_app.ui.multi_asset import open_split_dialog
from financial_app.ui.recurring_rules import open_rule_dialog
from financial_app.ui.save_warnings import show_warnings
from financial_app.ui.undo import offer_undo


def open_transaction_dialog(
    engine: Engine,
    rates: NbpRates,
    on_saved: Callable[[], None],
    transaction: Transaction | None = None,
    *,
    start_with: FormPrefill | None = None,
    link: Callable[[TransactionDraft], TransactionDraft] | None = None,
    on_rules_changed: Callable[[], None] | None = None,
) -> None:
    """Open a fresh dialog for a new Transaction (``None``), filled with ``start_with`` if given, or for editing or
    deleting ``transaction``.

    It is built on demand and removed when closed; ``on_saved`` runs after a save or a delete. ``link`` turns what it
    saves into the Transaction covering a Recurring Rule's occurrence (issue #97). With ``on_rules_changed`` an edited
    Deposit or Buy offers "Powtarzaj…", a new Recurring Rule repeating it, and ``on_rules_changed`` runs once it is
    saved. Its rules live in ``domain/transaction_form.py``; the dialog only binds its widgets to them.
    """
    dialog = movable_dialog()
    dialog.on("hide", dialog.delete)
    form = TransactionForm(
        FormContext(
            accounts=list_accounts(engine),
            instruments=list_instruments(engine),
            transactions=transactions_in_entry_order(engine),
            held_series={series.name: series for series in list_bond_series(engine).values()},
            mf_terms=load_series_terms(engine),
            bond_data=load_bond_data(engine),
            rates=rates.before,
            edited=transaction,
        )
    )
    with dialog, ui.card().classes("w-[460px]"):
        ui.label("Nowa transakcja" if transaction is None else "Edytuj transakcję").classes("text-lg font-bold")
        if not form.accounts:
            ui.label("Najpierw dodaj konto w zakładce Ustawienia.").classes("k-muted")
            with ui.row().classes("w-full justify-end"):
                ui.button("Zamknij", on_click=dialog.close).props("flat")
            dialog.open()
            return

        start = form.initial_state(date.today(), start_with)
        texts = start.texts
        # The Account comes first and stands out (#118): it decides the type's fields, Cash currencies and bond mode
        account = ui.select(form.accounts, label="Konto", value=start.account_id).props("filled")
        # The Theme's highlighted field (k-field): light blue in Jasny, dark gold in Golden
        account.classes("w-full k-field [&_.q-field\\_\\_native]:font-bold").mark("transaction-account")
        transaction_type = ui.select(TRANSACTION_TYPE_OPTIONS, label="Typ", value=start.kind.value)
        transaction_type.classes("w-full").mark("transaction-type")
        target = ui.select(form.targets, label="Na konto", value=start.target_id).classes("w-full")
        target.mark("transaction-target-account")
        day = ui.input("Data", value=start.day).classes("w-full").mark("transaction-date")
        with day.add_slot("append"):
            icon = ui.icon("event").classes("cursor-pointer")
            with ui.menu() as menu:
                ui.date(mask="DD.MM.YYYY").bind_value(day).on_value_change(menu.close)
            icon.on("click", menu.open)

        with ui.column().classes("w-full gap-0") as exchange_fields:
            directions = {BUY_CURRENCY: "PLN → waluta", SELL_CURRENCY: "waluta → PLN"}
            direction = ui.select(directions, label="Kierunek", value=start.direction).classes("w-full")
            direction.mark("transaction-direction")
            exchange_currency = ui.select([], label="Waluta").classes("w-full").mark("transaction-currency")
            foreign_amount = ui.input(value=texts.foreign_amount).classes("w-full")
            foreign_amount.mark("transaction-foreign-amount")
        cash_currency = ui.select([start.cash_currency], label="Waluta", value=start.cash_currency).classes("w-full")
        cash_currency.mark("transaction-cash-currency")
        amount = ui.input("Kwota (zł)", value=texts.amount).classes("w-full").mark("transaction-amount")
        with ui.column().classes("w-full gap-0") as instrument_fields:
            bond_mode = ui.checkbox("Obligacje skarbowe detaliczne", value=start.bond_mode)
            bond_mode.mark("transaction-bond-mode")
            bond_type = ui.select(BOND_TYPE_OPTIONS, label="Rodzaj obligacji", value=start.bond_type.value)
            bond_type.classes("w-full").mark("transaction-bond-type")
            # Any Series of the type may be picked, e.g. for an older purchase (L-26); the date's own is the default
            series_choice = ui.select({}, label="Seria", with_input=True).classes("w-full")
            series_choice.mark("transaction-bond-series-choice")
            series_text = ui.label().classes("text-sm k-muted").mark("transaction-bond-series")
            bond_hint = ui.label().classes("text-sm k-muted").mark("transaction-bond-hint")
            rollover = ui.checkbox("z rolowania", value=start.rollover).mark("transaction-rollover")
            # A Dividend without an Instrument is interest, e.g. on the Account's cash
            instrument = ui.select(form.instruments, label="Instrument", value=start.instrument_id, clearable=True)
            instrument.classes("w-full").mark("transaction-instrument")
            # An Early Redemption names the Lot it redeems (ADR-0007)
            lot = ui.select({}, label="Partia").classes("w-full").mark("transaction-lot")
            if not form.instruments:
                ui.label("Najpierw dodaj instrument w zakładce Ustawienia.").classes("k-muted")
            own_dividend_currency = start.dividend_currency
            dividend_currency = ui.select(
                [own_dividend_currency] if own_dividend_currency else [], label="Waluta", value=own_dividend_currency
            )
            dividend_currency.classes("w-full")
            dividend_currency.mark("transaction-dividend-currency")
            # A Buy's amount to spend proposes the quantity (#120); it is not saved
            spend = ui.input(value=texts.spend).classes("w-full").mark("transaction-spend")
            spend.props('hint="Proponuje liczbę; nie jest zapisywana"')
            quantity = ui.input("Liczba", value=texts.quantity).classes("w-full").mark("transaction-quantity")
            ratio = ui.input("Split (X:Y)", value=texts.ratio).classes("w-full").mark("transaction-split-ratio")
            ratio.props('hint="X nowych jednostek za każde Y dotychczasowych, np. 2:1"')
            price = ui.input("Cena (zł)", value=texts.price).classes("w-full").mark("transaction-price")
            gross = ui.input(value=texts.gross).classes("w-full").mark("transaction-gross")
            withholding_tax = ui.input(value=texts.withholding_tax).classes("w-full")
            withholding_tax.mark("transaction-withholding-tax")
            net = ui.label().classes("text-sm k-muted").mark("transaction-net")
        # How it is paid; outside the Instrument fields, as a foreign Deposit or Withdrawal takes a rate too
        paid_from = ui.select({}, label="Płatność").classes("w-full").mark("transaction-paid-from")
        fx_rate = ui.input(value=texts.fx_rate)
        fx_rate.classes("w-full").mark("transaction-fx-rate")
        commission = ui.input("Prowizja (zł)", value=texts.commission).classes("w-full")
        commission.mark("transaction-commission")
        cash_hint = ui.label().classes("text-sm text-negative").mark("transaction-cash-hint")
        convert = ui.checkbox(value=start.convert).mark("transaction-conversion")
        charged = ui.input("Kwota pobrana przez brokera (zł)", value=texts.charged).classes("w-full")
        charged.props('hint="Za liczbę × cenę, bez prowizji"').mark("transaction-charged")
        auto_exchange = ui.checkbox("Wymień walutę automatycznie").mark("transaction-auto-exchange")
        comment = ui.input("Komentarz", value=texts.comment).classes("w-full").mark("transaction-comment")
        error = ui.label().classes("text-negative").mark("transaction-error")

        picked: list[str | None] = [None]  # a Series the user picked instead of the one the date gives
        offered: list[tuple[list[str], str | None] | None] = [None]  # the Series list and value shown last
        syncing = [False]  # set while the dialog itself fills the Series list
        # Set while a layout is applied, and set again when a value it sets asks for another one
        applying, again = [False], [False]

        def state() -> FormState:
            return FormState(
                account_id=account.value,
                kind=TransactionType(transaction_type.value),
                day=day.value or "",
                texts=FormTexts(
                    amount=amount.value or "",
                    foreign_amount=foreign_amount.value or "",
                    quantity=quantity.value or "",
                    price=price.value or "",
                    fx_rate=fx_rate.value or "",
                    commission=commission.value or "",
                    charged=charged.value or "",
                    gross=gross.value or "",
                    withholding_tax=withholding_tax.value or "",
                    ratio=ratio.value or "",
                    comment=comment.value or "",
                    spend=spend.value or "",
                ),
                target_id=target.value,
                instrument_id=instrument.value,
                bond_mode=bool(bond_mode.value),
                bond_type=BondType(bond_type.value),
                series_pick=picked[0],
                rollover=bool(rollover.value),
                lot_id=lot.value,
                direction=direction.value,
                exchange_currency=exchange_currency.value,
                cash_currency=cash_currency.value,
                dividend_currency=dividend_currency.value,
                paid_from=paid_from.value,
                convert=bool(convert.value),
                auto_exchange=bool(auto_exchange.value),
            )

        def update() -> None:
            """Show the fields the form's state needs; a value it sets that changes the state runs it once more."""
            if applying[0]:
                again[0] = True
                return
            applying[0] = True
            try:
                for _ in range(5):  # settles in one or two rounds
                    again[0] = False
                    apply(form.layout(state()))
                    if not again[0]:
                        break
            finally:
                applying[0] = False

        def apply(layout: FormLayout) -> None:
            transaction_type.set_options(dict(layout.kind.options), value=layout.kind.value)
            amount.visible = layout.amount.visible
            amount.props(f'label="{layout.amount.label}"')
            instrument_fields.visible = layout.instrument_fields
            target.visible = layout.target.visible
            target.set_options(dict(layout.target.options), value=layout.target.value)
            ratio.visible = layout.ratio
            exchange_fields.visible = layout.exchange_fields
            dividend_currency.visible = layout.dividend_currency.visible
            if layout.dividend_currency.visible:
                currencies = list(layout.dividend_currency.options)
                dividend_currency.set_options(currencies, value=layout.dividend_currency.value)
            spend.visible = layout.spend.visible
            spend.props(f'label="{layout.spend.label}"')
            quantity.visible = layout.quantity.visible
            quantity.props(f'label="{layout.quantity.label}"')
            bond_mode.visible = layout.bond_mode
            for bond_field in (bond_type, series_choice, series_text):
                bond_field.visible = layout.bond_fields
            instrument.set_options(dict(layout.instruments.options), value=layout.instruments.value)
            instrument.visible = layout.instrument
            price.visible = layout.price.visible
            price.props(f'label="{layout.price.label}"')
            commission.visible = layout.commission.visible
            commission.props(f'label="{layout.commission.label}"')
            rollover.visible = layout.rollover
            if layout.bond_fields:
                list_series(layout.series.options, layout.series.value)
            series_text.text = layout.series_text
            bond_hint.text = layout.bond_hint
            bond_hint.visible = bool(layout.bond_hint)
            lot.visible = layout.lot.visible
            if layout.lot.visible:
                lot.set_options(dict(layout.lot.options), value=layout.lot.value)
            gross.visible = layout.gross.visible
            gross.props(f'label="{layout.gross.label}"')
            withholding_tax.visible = layout.withholding_tax.visible
            withholding_tax.props(f'label="{layout.withholding_tax.label}"')
            net.visible = layout.net.visible
            prefill_redemption()
            propose_quantity()
            show_net()
            show_cash_hint()
            fx_rate.visible = layout.fx_rate.visible
            fx_rate.props(f'label="{layout.fx_rate.label}" hint="{layout.fx_rate.hint}"')
            paid_from.visible = layout.paid_from.visible
            paid_from.props(f'label="{layout.paid_from.label}"')
            if layout.paid_from.visible:
                paid_from.set_options(dict(layout.paid_from.options), value=layout.paid_from.value)
            convert.visible = layout.convert.visible
            if layout.convert.label:
                convert.text = layout.convert.label
            charged.visible = layout.charged.visible
            charged.props(f'label="{layout.charged.label}" hint="{layout.charged.hint}"')
            cash_currency.visible = layout.cash_currency.visible
            cash_currency.set_options(list(layout.cash_currency.options), value=layout.cash_currency.value)
            auto_exchange.visible = layout.auto_exchange
            exchange_currency.set_options(list(layout.exchange_currency.options), value=layout.exchange_currency.value)
            direction.set_options(dict(layout.direction.options), value=layout.direction.value)
            foreign_amount.props(f'label="{layout.foreign_amount.label}"')

        def list_series(options: Mapping[str, str], value: str | None) -> None:
            """Offer the type's Series, sending the list only when it changed."""
            if (list(options), value) == offered[0]:
                return  # nothing to send again
            offered[0] = (list(options), value)
            syncing[0] = True
            try:
                series_choice.set_options(dict(options), value=value)
            finally:
                syncing[0] = False

        def series_picked() -> None:
            if syncing[0]:
                return
            value = series_choice.value
            picked[0] = None if value is None or value == form.date_series(state()) else str(value)
            update()
            bond_price()

        def type_changed() -> None:
            picked[0] = None  # a Series of another type is not one of this type

        def show_net() -> None:
            net.text = form.net_text(state())

        def show_cash_hint() -> None:
            cash_hint.text = form.cash_hint(state())
            cash_hint.visible = bool(cash_hint.text)

        set_price = [""]  # the price the bond mode set last, which it may set again
        # What the Early Redemption prefill set last in each field, which it may set again; a value the user typed (or
        # the edited Sell's own) stays
        prefilled: dict[ui.input, str] = {}
        prefilling = [False]

        def prefill(field: ui.input, value: str) -> None:
            if not field.value.strip() or field.value == prefilled.get(field):
                prefilled[field] = value
                field.value = value

        def prefill_redemption() -> None:
            """Fill an Early Redemption with the chosen Lot's bonds, one bond's gross value as the price, the fee as
            the commission and the tax the Account's Tax Regime withholds (spec 3.4.1)."""
            if prefilling[0] or not form.redeems_bonds(state()):
                return
            prefilling[0] = True
            try:
                units = form.lot_quantity(state())
                if units is None:
                    return
                prefill(quantity, units)
                redemption = form.redemption(state())
                if redemption is None:
                    return
                prefill(price, format_exact(redemption.price))
                prefill(commission, format_exact(redemption.fee))
                prefill(withholding_tax, format_exact(redemption.tax))
            finally:
                prefilling[0] = False

        def propose_quantity() -> None:
            """Fill the quantity the amount to spend buys, until the user types a quantity of their own (#120)."""
            proposal = form.proposed_quantity(state())
            if proposal is not None:
                prefill(quantity, proposal)

        def bond_price(rollover_changed: bool = False) -> None:
            """Price the bond mode's purchase: 100 zł, or the Rollover price of the Series. A price the user typed (or
            the edited Buy's own) stays unless the Rollover is switched."""
            value = form.bond_price(state())
            if value is None:
                return
            if not rollover_changed and price.value.strip() and price.value != set_price[0]:
                return
            price.value = set_price[0] = value

        def account_changed() -> None:
            # A new Buy follows the Account: the bond mode on a Bonds Account, else an Instrument
            if transaction is None:
                bond_mode.value = form.bond_mode_for(account.value)

        update()
        if transaction is None:
            bond_price()
        account.on_value_change(account_changed)
        rollover.on_value_change(lambda: bond_price(rollover_changed=True))
        rollover.on_value_change(update)
        series_choice.on_value_change(series_picked)
        bond_type.on_value_change(type_changed)  # before the handlers that read the chosen Series
        for bond_field in (bond_mode, bond_type, day, transaction_type):
            bond_field.on_value_change(lambda: bond_price())
        for field in (
            transaction_type,
            account,
            instrument,
            direction,
            exchange_currency,
            cash_currency,
            dividend_currency,
            paid_from,
            convert,
            bond_mode,
            bond_type,
            day,
        ):
            field.on_value_change(update)
        for redemption_input in (lot, quantity):
            redemption_input.on_value_change(prefill_redemption)
        for net_input in (gross, withholding_tax, quantity, price, commission):
            net_input.on_value_change(show_net)
        for cash_input in (amount, foreign_amount, quantity, price, commission, fx_rate, charged):
            cash_input.on_value_change(show_cash_hint)
        for proposal_input in (spend, price, commission, fx_rate):
            proposal_input.on_value_change(propose_quantity)

        def save() -> None:
            form_state = state()
            try:
                saved = save_transaction(
                    engine,
                    lambda series_id: (link or _unlinked)(form.draft(form_state, series_id)),
                    edited=transaction,
                    series=form.series_to_buy(form_state),
                    with_exchange=form.with_exchange(form_state),
                )
            except (TransactionError, MissingNbpRateError, InstrumentError) as exc:
                error.text = str(exc)
                return
            dialog.close()
            # The dialog asks for a Multi-asset Split itself, so it is no warning here
            show_warnings(saved.warnings, unsplit=False)
            on_saved()
            for unsplit in saved.warnings.unsplit:
                open_split_dialog(engine, unsplit, on_saved)

        def restore(deleted: Transaction) -> None:
            try:
                restored = restore_saved(engine, deleted)
            except TransactionError as exc:
                ui.notify(f"Nie można cofnąć usunięcia. {exc}", type="negative", multi_line=True)
                return
            show_warnings(restored.warnings, "Przywrócono")
            on_saved()

        def delete() -> None:
            assert transaction is not None
            gone = transaction
            try:
                deleted = delete_saved(engine, gone.id)
            except TransactionError as exc:
                error.text = f"Nie można usunąć tej transakcji. {exc}"
                return
            dialog.close()
            show_warnings(deleted.warnings, "Usunięto")
            on_saved()
            # No "are you sure?": the bar offers to put the Transaction back for a few seconds
            offer_undo("Usunięto transakcję.", lambda: restore(gone))

        with ui.row().classes("w-full items-center"):
            if transaction is not None:
                delete_button = ui.button("Usuń", on_click=delete)
                delete_button.props("flat color=negative").mark("delete-transaction")
            if (
                transaction is not None
                and on_rules_changed is not None
                and transaction.transaction_type in RECURRING_TYPES
            ):

                def repeat() -> None:
                    assert transaction is not None and on_rules_changed is not None
                    dialog.close()
                    today = rates.today()
                    open_rule_dialog(engine, today, on_rules_changed, defaults=repeating(transaction, today))

                ui.button("Powtarzaj…", on_click=repeat).props("flat no-caps").mark("repeat-transaction").tooltip(
                    "Nowa reguła cykliczna na wzór tej transakcji"
                )
            ui.space()
            ui.button("Anuluj", on_click=dialog.close).props("flat")
            ui.button("Zapisz" if transaction is None else "Zapisz zmiany", on_click=save)
    dialog.open()


def _unlinked(draft: TransactionDraft) -> TransactionDraft:
    return draft
