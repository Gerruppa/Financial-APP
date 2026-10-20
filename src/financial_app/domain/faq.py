"""The Pomoc tab's FAQ (issue #156): its Markdown text read into sections and questions, and the search over them.

The text is kept apart from the UI code, so answers grow without touching it. A section is a ``# Title`` line, a
question a ``## Question? {#slug}`` line under it; an optional ``Przejdź do: /path`` line right below the question
names the tab its answer is about, and the Markdown up to the next heading is the answer.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from financial_app.domain.formatting import folded

_SECTION = re.compile(r"^# (?P<title>.+?)\s*$")
_QUESTION = re.compile(r"^## (?P<title>.+?)\s*(?:\{#(?P<slug>[a-z0-9-]+)\})?\s*$")
_GOTO = re.compile(r"^Przejdź do: (?P<path>/\S*)\s*$")


class FaqError(ValueError):
    """The FAQ text breaks its format; the message names the entry (Polish)."""


@dataclass(frozen=True)
class Question:
    slug: str
    title: str
    answer: str
    # The path of the tab the answer is about, opened by its "Przejdź do …" button
    goto: str | None = None


@dataclass(frozen=True)
class Section:
    title: str
    questions: tuple[Question, ...]


@dataclass
class _Reading:
    """The question being read: its heading, slug, the tab it names and its answer's lines so far."""

    title: str
    slug: str
    goto: str | None = None
    lines: list[str] = field(default_factory=list)

    def question(self) -> Question:
        answer = "\n".join(self.lines).strip()
        if not answer:
            raise FaqError(f"Pytanie „{self.title}” ma pustą odpowiedź.")
        return Question(self.slug, self.title, answer, self.goto)


def parse_faq(text: str) -> list[Section]:
    """The sections in the text's order; each needs a question, and each question a slug of its own and an answer."""
    # Each section's title with its questions read so far
    read: list[tuple[str, list[Question]]] = []
    current: _Reading | None = None
    slugs: set[str] = set()

    def finish() -> None:
        if current is not None:
            read[-1][1].append(current.question())

    for line in text.splitlines():
        if heading := _SECTION.match(line):
            finish()
            current = None
            read.append((heading["title"], []))
        elif asked := _QUESTION.match(line):
            finish()
            if not read:
                raise FaqError(f"Pytanie „{asked['title']}” stoi przed pierwszą sekcją.")
            title, slug = asked["title"], asked["slug"]
            if slug is None:
                raise FaqError(f"Pytanie „{title}” nie ma slugu {{#…}}.")
            if slug in slugs:
                raise FaqError(f"Slug #{slug} powtarza się.")
            slugs.add(slug)
            current = _Reading(title, slug)
        elif current is not None:
            if (target := _GOTO.match(line)) and current.goto is None and not any(current.lines):
                current.goto = target["path"]
            else:
                current.lines.append(line)
        elif line.strip():
            raise FaqError(f"Tekst „{line.strip()}” stoi przed pierwszą sekcją.")
    finish()
    if not read:
        raise FaqError("FAQ nie ma żadnej sekcji.")
    for title, questions in read:
        if not questions:
            raise FaqError(f"Sekcja „{title}” nie ma pytań.")
    return [Section(title, tuple(questions)) for title, questions in read]


def matching(sections: Iterable[Section], query: str) -> list[Question]:
    """The questions whose title or answer contains ``query``, ignoring case and Polish letters; all for none."""
    wanted = folded(query.strip())
    return [
        question
        for section in sections
        for question in section.questions
        if wanted in folded(question.title) or wanted in folded(question.answer)
    ]
