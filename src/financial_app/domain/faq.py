"""The Pomoc tab's FAQ (issue #156): its Markdown text read into sections and questions, and the search over them.

The text is kept apart from the UI code, so answers grow without touching it. A section is a ``# Title`` line, a
question a ``## Question? {#slug}`` line under it; an optional ``Przejdź do: /path`` line right below the question
names the tab its answer is about, and the Markdown up to the next heading is the answer.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field

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


@dataclass
class Section:
    title: str
    questions: list[Question] = field(default_factory=list)


def parse_faq(text: str) -> list[Section]:
    """The sections in the text's order; each needs a question, and each question a slug of its own and an answer."""
    sections: list[Section] = []
    # The question being read: its heading, slug, goto and answer lines
    current: tuple[str, str, str | None, list[str]] | None = None
    slugs: set[str] = set()

    def finish() -> None:
        if current is None:
            return
        title, slug, goto, lines = current
        answer = "\n".join(lines).strip()
        if not answer:
            raise FaqError(f"Pytanie „{title}” ma pustą odpowiedź.")
        sections[-1].questions.append(Question(slug, title, answer, goto))

    for line in text.splitlines():
        if heading := _SECTION.match(line):
            finish()
            current = None
            sections.append(Section(heading["title"]))
        elif asked := _QUESTION.match(line):
            finish()
            if not sections:
                raise FaqError(f"Pytanie „{asked['title']}” stoi przed pierwszą sekcją.")
            title, slug = asked["title"], asked["slug"]
            if slug is None:
                raise FaqError(f"Pytanie „{title}” nie ma slugu {{#…}}.")
            if slug in slugs:
                raise FaqError(f"Slug #{slug} powtarza się.")
            slugs.add(slug)
            current = (title, slug, None, [])
        elif current is not None:
            title, slug, goto, lines = current
            if (target := _GOTO.match(line)) and goto is None and not any(lines):
                current = (title, slug, target["path"], lines)
            else:
                lines.append(line)
        elif line.strip():
            raise FaqError(f"Tekst „{line.strip()}” stoi przed pierwszą sekcją.")
    finish()
    if not sections:
        raise FaqError("FAQ nie ma żadnej sekcji.")
    for section in sections:
        if not section.questions:
            raise FaqError(f"Sekcja „{section.title}” nie ma pytań.")
    return sections


def matching(sections: Iterable[Section], query: str) -> list[Question]:
    """The questions whose title or answer contains ``query``, ignoring case and Polish letters; all for none."""
    wanted = _folded(query.strip())
    return [
        question
        for section in sections
        for question in section.questions
        if wanted in _folded(question.title) or wanted in _folded(question.answer)
    ]


def _folded(text: str) -> str:
    """``text`` in lower case without diacritics, so "zaczac" finds "zacząć"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold().replace("ł", "l"))
    return "".join(char for char in decomposed if not unicodedata.combining(char))
