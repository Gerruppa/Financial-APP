"""The Investment Goal tile on the Dashboard (issue #96): the View Scope's goal with its progress and real forecast,
the pencil opening the dialog that sets it as an amount or for FIRE."""

from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.currencies import MissingNbpRateError
from financial_app.domain.formatting import format_date, format_month, format_percent, format_pln
from financial_app.domain.investment_goal import (
    AVERAGE_MONTHS,
    FORECAST_MONTHS,
    GoalError,
    GoalMode,
    GoalTexts,
    InvestmentGoal,
    average_monthly_deposits,
    forecast,
    parse_goal,
    rules_monthly_deposits,
)
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.recurring import RecurringRule
from financial_app.domain.transactions import PLN
from financial_app.persistence.investment_goals import delete_goal, load_goal, save_goal
from financial_app.persistence.recurring_rules import list_rules
from financial_app.sources.current_prices import LatestRates
from financial_app.ui.dialogs import movable_dialog
from financial_app.ui.info import card_title

GOAL_INFO = (
    "Wartość, do której dąży ten widok: kwota podana wprost albo cel FIRE, czyli roczne wydatki podzielone przez "
    "stopę bezpiecznej wypłaty (4% to 25 × wydatki). Postęp to dzisiejsza wartość z Dashboardu, po podatku gdy "
    "włączony jest przełącznik „Po podatku”.\n\n"
    "Prognoza jest realna, w dzisiejszych złotych: zakłada oczekiwaną roczną stopę zwrotu po inflacji i "
    "miesięczną wpłatę. Domyślnie to wpłaty z aktywnych reguł cyklicznych tego widoku, przeliczone na miesiąc i "
    "na złote (na koncie także transfery gotówki na nie, minus transfery z niego); bez takich reguł średnia wpłat "
    "netto z ostatnich 12 miesięcy."
)


def goal_tile(
    engine: Engine,
    rates: LatestRates,
    account_id: int | None,
    value: Decimal,
    history: Sequence[DayValue] | None,
    today: date,
    on_saved: Callable[[], None],
) -> None:
    """The goal of the View Scope ``account_id`` at today's ``value``; its active Recurring Rules give the default
    monthly deposit (#148), else ``history`` (``None`` while it is computed) does. Without a goal, the "Ustaw cel"
    button."""
    goal = load_goal(engine, account_id)
    rules = list_rules(engine)
    from_rules = rules_monthly_deposits(rules, account_id, today, _latest_rates(rules, rates))
    if from_rules is not None:
        average: Decimal | None = from_rules
        default = f"z reguł cyklicznych: {format_pln(from_rules)}"
    elif history is None:
        average, default = None, "historia jeszcze się liczy"
    else:
        average = average_monthly_deposits(history, account_id, today)
        default = f"średnia z {AVERAGE_MONTHS} miesięcy: {format_pln(average)}"

    def edit() -> None:
        _goal_dialog(engine, account_id, goal, default, on_saved)

    with ui.card().classes("w-full gap-1").mark("investment-goal"):
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            card_title("Cel inwestycyjny", GOAL_INFO, "investment-goal")
            if goal is not None:
                ui.button(icon="edit", on_click=edit).props('flat round dense aria-label="Zmień cel"').mark("edit-goal")
        if goal is None:
            ui.button("Ustaw cel", icon="flag", on_click=edit).props("flat no-caps").mark("set-goal")
            return
        monthly = goal.monthly_deposit if goal.monthly_deposit is not None else average
        result = forecast(goal, value, monthly or Decimal(0), today)
        percent = format_percent(result.progress * 100, decimals=0)
        ui.label(f"Cel: {format_pln(result.target)} · {percent}").classes("text-xl font-medium").mark("goal-progress")
        ui.linear_progress(value=float(min(max(result.progress, Decimal(0)), Decimal(1))), show_value=False).props(
            "rounded size=10px"
        )
        if result.reached:
            text = "Cel osiągnięty"
        elif monthly is None:
            text = "Prognoza: wyliczanie historii…"
        elif result.reached_on is None:
            text = f"Poza zasięgiem: prognoza nie dochodzi do celu w ciągu {FORECAST_MONTHS // 12} lat"
        else:
            text = (
                f"Prognoza: cel w {format_month(result.reached_on)} przy wpłatach {format_pln(monthly)} miesięcznie "
                f"i {format_percent(goal.real_return)} realnie rocznie"
            )
        ui.label(text).classes("text-sm text-gray-600").mark("goal-forecast")
        if goal.target_date is not None and not result.reached:
            if result.required_monthly is None:
                required = f"Data docelowa {format_date(goal.target_date)} minęła"
            else:
                required = (
                    f"Do {format_date(goal.target_date)} potrzeba {format_pln(result.required_monthly)} miesięcznie"
                )
            ui.label(required).classes("text-sm text-gray-600").mark("goal-required")


def _latest_rates(rules: Sequence[RecurringRule], rates: LatestRates) -> dict[str, Decimal]:
    """The latest NBP Rate of each foreign currency of ``rules`` there is one for."""
    found = {}
    for currency in {rule.currency for rule in rules} - {PLN}:
        try:
            found[currency] = rates.latest(currency).rate
        except MissingNbpRateError:
            pass
    return found


def _goal_dialog(
    engine: Engine,
    account_id: int | None,
    goal: InvestmentGoal | None,
    default: str,
    on_saved: Callable[[], None],
) -> None:
    """Set the View Scope's goal (``goal`` the one it has, if any) as an amount or for FIRE, or remove it;
    ``default`` says where the monthly deposit left empty comes from."""
    texts = GoalTexts() if goal is None else GoalTexts.of(goal)
    # At the page's root, so that the Dashboard redrawing meanwhile (e.g. History computed) leaves it open
    with ui.context.client.content:
        dialog = movable_dialog()
    dialog.on("hide", dialog.delete)
    with dialog, ui.card().classes("w-[480px]").mark("goal-dialog"):
        ui.label("Cel inwestycyjny").classes("text-lg font-bold")
        mode = ui.toggle(
            {GoalMode.AMOUNT.value: "Kwota", GoalMode.FIRE.value: "FIRE: wydatki roczne + stopa wypłaty"},
            value=(GoalMode.AMOUNT if goal is None else goal.mode).value,
        ).mark("goal-mode")
        amount = ui.input("Kwota celu", value=texts.amount).props('suffix="zł"').classes("w-full").mark("goal-amount")
        amount.bind_visibility_from(mode, "value", value=GoalMode.AMOUNT.value)
        with ui.row().classes("w-full no-wrap") as fire:
            expenses = ui.input("Wydatki roczne", value=texts.yearly_expenses).props('suffix="zł"').classes("flex-1")
            expenses.mark("goal-expenses")
            withdrawal = ui.input("Stopa wypłaty", value=texts.withdrawal_rate).props('suffix="%"').classes("w-32")
            withdrawal.mark("goal-withdrawal-rate")
        fire.bind_visibility_from(mode, "value", value=GoalMode.FIRE.value)
        target_date = ui.input("Data docelowa (opcjonalnie)", value=texts.target_date, placeholder="dd.mm.rrrr")
        target_date.classes("w-full").mark("goal-target-date")
        ui.label("Założenia prognozy (realnie, w dzisiejszych złotych)").classes("text-sm font-medium pt-2")
        real_return = ui.input("Oczekiwana roczna stopa zwrotu", value=texts.real_return).props('suffix="%"')
        real_return.classes("w-full").mark("goal-real-return")
        monthly = ui.input("Miesięczna wpłata (puste: domyślna)", value=texts.monthly_deposit).props('suffix="zł"')
        monthly.classes("w-full").mark("goal-monthly")
        ui.label(f"Domyślnie {default}").classes("text-xs text-gray-500").mark("goal-monthly-default")
        error = ui.label().classes("text-negative").mark("goal-error")

        def save() -> None:
            typed = GoalTexts(
                amount=amount.value,
                yearly_expenses=expenses.value,
                withdrawal_rate=withdrawal.value,
                target_date=target_date.value,
                real_return=real_return.value,
                monthly_deposit=monthly.value,
            )
            try:
                saved = parse_goal(account_id, GoalMode(mode.value), typed)
            except GoalError as refusal:
                error.set_text(str(refusal))
                return
            save_goal(engine, saved)
            dialog.close()
            on_saved()

        def remove() -> None:
            delete_goal(engine, account_id)
            dialog.close()
            on_saved()

        with ui.row().classes("w-full justify-end"):
            if goal is not None:
                ui.button("Usuń cel", on_click=remove).props("flat color=negative").mark("goal-delete")
            ui.space()
            ui.button("Anuluj", on_click=dialog.close).props("flat")
            ui.button("Zapisz cel", on_click=save).mark("goal-save")
    dialog.open()
