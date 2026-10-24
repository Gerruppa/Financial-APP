"""The Pomoc tab (issue #156): the FAQ, each answer a collapsible item, with a search filtering the questions.

The text lives in ``faq.md`` beside this module (format in ``domain/faq.py``), so answers grow without touching the
code. An answer about a tab has a "Przejdź do …" button opening it, also when the tab is hidden from the menu.
"""

from collections.abc import Mapping
from importlib.resources import files

from nicegui import ui

from financial_app.domain.faq import Section, matching, parse_faq

HELP_PATH = "/pomoc"


def load_faq() -> list[Section]:
    """The FAQ shipped with the app."""
    return parse_faq(files(__package__).joinpath("faq.md").read_text(encoding="utf-8"))


def build_help_page(tab_labels: Mapping[str, str]) -> None:
    """The tab; ``tab_labels`` names the tabs by path, for the "Przejdź do …" buttons."""
    faq = load_faq()
    with ui.column().classes("w-full max-w-4xl").mark("help"):
        ui.label("Pomoc").classes("text-2xl font-bold")
        ui.label("Najczęstsze pytania. Kliknij pytanie, aby zobaczyć odpowiedź.").classes("k-muted")
        search = ui.input("Szukaj w pytaniach i odpowiedziach").props("clearable").classes("w-full")
        search.mark("faq-search")
        with search.add_slot("prepend"):
            ui.icon("search")
        sections: list[tuple[ui.column, list[tuple[str, ui.expansion]]]] = []
        for section in faq:
            with ui.column().classes("w-full gap-1 pt-2") as column:
                ui.label(section.title).classes("text-lg font-bold")
                items: list[tuple[str, ui.expansion]] = []
                for question in section.questions:
                    expansion = ui.expansion(question.title).classes("w-full k-faq")
                    with expansion.mark(f"faq-{question.slug}"):
                        ui.markdown(question.answer).classes("text-sm")
                        if question.goto is not None:
                            label = tab_labels.get(question.goto, question.goto)
                            ui.button(
                                f"Przejdź do: {label}",
                                icon="arrow_forward",
                                on_click=lambda path=question.goto: ui.navigate.to(path),
                            ).props("flat no-caps").mark(f"faq-{question.slug}-go")
                    items.append((question.slug, expansion))
            sections.append((column, items))
        no_match = ui.label("Żadne pytanie nie pasuje do wyszukiwania.").classes("k-muted pt-2")
        no_match.mark("faq-no-match")
        no_match.visible = False

    def filter_questions() -> None:
        shown = {question.slug for question in matching(faq, search.value or "")}
        for column, items in sections:
            for slug, expansion in items:
                expansion.visible = slug in shown
            column.visible = any(slug in shown for slug, _ in items)
        no_match.visible = not shown

    search.on_value_change(filter_questions)
