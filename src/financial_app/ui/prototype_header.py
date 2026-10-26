"""PROTOTYPE, wipe me (issue #176 follow-up): three header variants for the bell, switched by ``?variant=A|B|C``.

A: the bell replaces both "do zatwierdzenia" counters.  B: counters stay but shrink to an icon with a number.
C: like A, but the bell's badge shows how many reminders are unread instead of a dot."""

from datetime import date

from nicegui import ui
from sqlalchemy import Engine

from financial_app.persistence.bond_drafts import pending_drafts
from financial_app.persistence.deposit_drafts import pending_deposit_drafts
from financial_app.persistence.recurring_rules import pending_recurring_drafts

VARIANTS = {"A": "Dzwonek zastępuje liczniki", "B": "Liczniki jako ikony", "C": "Dzwonek z liczbą"}


def current_variant() -> str:
    variant = str(ui.context.client.request.query_params.get("variant", "A")).upper()
    return variant if variant in VARIANTS else "A"


def compact_counts(engine: Engine, today: date) -> None:
    for icon, count, path, tip in (
        (
            "task_alt",
            len(pending_drafts(engine, today)) + len(pending_deposit_drafts(engine, today)),
            "/obligacje",
            "Do zatwierdzenia",
        ),
        ("event_repeat", len(pending_recurring_drafts(engine, today)), "/transakcje", "Cykliczne do zatwierdzenia"),
    ):
        if count:
            button = ui.button(icon=icon, on_click=lambda path=path: ui.navigate.to(path)).props(
                "flat round color=attention"
            )
            button.tooltip(f"{tip}: {count}")
            with button:
                ui.badge(str(count)).props("rounded floating color=attention")


def switcher() -> None:
    keys = list(VARIANTS)
    here = current_variant()

    def other(step: int) -> str:
        return keys[(keys.index(here) + step) % len(keys)]

    with ui.page_sticky(position="bottom", y_offset=20).style("z-index: 3000"):
        with ui.row().classes("items-center gap-2 px-3 py-1 rounded-full bg-black text-white shadow-lg"):
            ui.button(icon="chevron_left", on_click=lambda: ui.navigate.to(f"/?variant={other(-1)}")).props(
                "flat round dense color=white"
            )
            ui.label(f"{here} ({VARIANTS[here]})").classes("text-sm")
            ui.button(icon="chevron_right", on_click=lambda: ui.navigate.to(f"/?variant={other(1)}")).props(
                "flat round dense color=white"
            )
