"""Showing what a save of Transactions warns of (#110), the same way wherever it was saved, and the fix the negative
PLN cash warning offers (#267): the covering Deposits that bring each Account's cash back to zero."""

from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal

from nicegui import context, ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_count, format_date, format_pln
from financial_app.domain.save_warnings import SaveWarnings
from financial_app.domain.transactions import COVERING_COMMENT, TransactionDraft, TransactionError
from financial_app.persistence.accounts import list_accounts
from financial_app.sources.transaction_saving import covering_proposals, save_covering
from financial_app.ui.dialogs import movable_dialog
from financial_app.ui.undo import HOLDS_BARS, action_bar

# How long the bar offering the covering Deposits stays; a module value so a test can shorten it
COVERING_SECONDS = 20.0


def show_warnings(
    warnings: SaveWarnings,
    done: str = "Zapisano",
    *,
    engine: Engine,
    on_saved: Callable[[], object] | None,
    unsplit: bool = True,
) -> None:
    """A warning notification per message; ``done`` and ``unsplit`` as in ``SaveWarnings.messages``. PLN cash below
    zero also gets the bar ``covering-bar`` offering its covering Deposits (``covering-button``, for
    ``COVERING_SECONDS``, above the undo bar); ``on_saved`` runs once they are saved."""
    for message in warnings.messages(done, unsplit=unsplit):
        ui.notify(message, type="warning", multi_line=True)
    if accounts := warnings.short_of_pln:
        action_bar(
            "covering",
            "Brakuje gotówki w PLN.",
            "Dodaj wpłaty uzupełniające",
            lambda: _covering_dialog(engine, accounts, on_saved),
            COVERING_SECONDS,
        )


def deposits_total(deposits: Iterable[TransactionDraft]) -> str:
    """E.g. "2 wpłaty, razem 3 200,00 zł"."""
    deposits = list(deposits)
    total = sum((deposit.actual_amount for deposit in deposits), Decimal(0))
    return f"{format_count(len(deposits), 'wpłatę', 'wpłaty', 'wpłat')}, razem {format_pln(total)}"


def deposit_choices(
    proposed: Mapping[int, list[TransactionDraft]],
    names: Mapping[int, str],
    ticked: Callable[[int], bool],
    keep: Callable[[int, bool], None],
    marker: str,
) -> None:
    """One checkbox per Account of the ``proposed`` covering Deposits (``<marker>-<id>``), its Deposits beneath;
    ``keep`` hears each tick. Shared by the negative cash window and the crypto import's step 4."""
    for account_id, deposits in proposed.items():
        ui.checkbox(
            f"{names.get(account_id, '')}: dodaj {deposits_total(deposits)}",
            value=ticked(account_id),
            on_change=lambda e, a=account_id: keep(a, bool(e.value)),
        ).mark(f"{marker}-{account_id}")
        with ui.column().classes("gap-0 pl-8"):
            for deposit in deposits:
                ui.label(f"{format_date(deposit.date)}: {format_pln(deposit.actual_amount)}").classes("text-sm")


def _covering_dialog(engine: Engine, account_ids: tuple[int, ...], on_saved: Callable[[], object] | None) -> None:
    """The proposed covering Deposits per Account (``covering-window``, checkboxes ``covering-account-<id>``),
    computed now, so they cover what is saved by then; "Zapisz wpłaty" (``covering-save``) saves the ticked ones."""
    proposed = covering_proposals(engine, account_ids)
    if not proposed:
        ui.notify("Gotówka w PLN nie spada już poniżej zera: nie ma czego uzupełniać.")
        return
    names = {account.id: account.name for account in list_accounts(engine)}
    kept = set(proposed)

    def keep(account_id: int, ticked: bool) -> None:
        if ticked:
            kept.add(account_id)
        else:
            kept.discard(account_id)

    # In the page's layout: the bar it was opened from is gone. It keeps the undo bar of the delete it may cover
    with context.client.layout:
        dialog = movable_dialog().classes(HOLDS_BARS)
    dialog.on("hide", dialog.delete)
    with dialog, ui.card().classes("w-[32rem] max-w-full").mark("covering-window"):
        ui.label("Wpłaty uzupełniające").classes("text-lg font-bold")
        ui.label(
            "Wpłata w każdym dniu, w którym gotówki brakuje, dokładnie na brakującą kwotę. Odznacz konto, jeśli "
            f"wpłaty wpiszesz sam. W Transakcjach mają komentarz „{COVERING_COMMENT}”: popraw ich datę albo kwotę, "
            "jeśli wiesz, kiedy i ile naprawdę wpłacałeś."
        ).classes("text-sm")
        deposit_choices(proposed, names, lambda _: True, keep, "covering-account")

        def save() -> None:
            deposits = [deposit for account_id in proposed if account_id in kept for deposit in proposed[account_id]]
            dialog.close()
            if not deposits:
                return
            try:
                saved = save_covering(engine, deposits)
            except TransactionError as exc:
                ui.notify(str(exc), type="negative", multi_line=True)
                return
            ui.notify(f"Dodano {deposits_total(deposits)}.", type="positive")
            show_warnings(saved.warnings, engine=engine, on_saved=on_saved)
            if on_saved is not None:
                on_saved()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Anuluj", on_click=dialog.close).props("flat no-caps").mark("covering-cancel")
            ui.button("Zapisz wpłaty", icon="save", on_click=save).props("no-caps").mark("covering-save")
    dialog.open()
