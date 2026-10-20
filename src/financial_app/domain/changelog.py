"""The changelog (issue #200): its Markdown read into Releases, and whether a version's first start announces it.

The text starts with ``# Historia zmian``. Each version is a ``## 1.1.0 — 2026-11-02`` heading, newest first, with an
optional summary paragraph and up to three groups, ``### Nowe funkcje``, ``### Poprawki`` and ``### Zmiany`` in that
order, each a list of ``- `` entries. A ``## Nieopublikowane`` section on top collects the entries until a release
numbers and dates it.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

TITLE = "Historia zmian"
UNRELEASED = "Nieopublikowane"
GROUPS = ("Nowe funkcje", "Poprawki", "Zmiany")

_TITLE = re.compile(r"^# (?P<title>.+?)\s*$")
_RELEASE = re.compile(r"^## (?P<heading>.+?)\s*$")
_VERSION = re.compile(r"^(?P<version>\d+\.\d+\.\d+) — (?P<date>\d{4}-\d{2}-\d{2})$")
_GROUP = re.compile(r"^### (?P<title>.+?)\s*$")
_ENTRY = re.compile(r"^- (?P<text>.+?)\s*$")


class ChangelogError(ValueError):
    """The changelog text breaks its format; the message names the entry (Polish)."""


@dataclass(frozen=True)
class Group:
    title: str
    entries: tuple[str, ...]


@dataclass(frozen=True)
class Release:
    version: str
    released: date
    summary: str
    groups: tuple[Group, ...]


@dataclass(frozen=True)
class Changelog:
    # The "Nieopublikowane" section's groups, none when it is missing or empty
    unreleased: tuple[Group, ...]
    # Newest first
    releases: tuple[Release, ...]

    def release(self, version: str) -> Release | None:
        return next((release for release in self.releases if release.version == version), None)


def version_key(version: str) -> tuple[int, ...]:
    """``1.10.0`` sorts after ``1.9.0``."""
    return tuple(int(part) for part in version.split("."))


@dataclass
class _Group:
    """A group being read: its title and its entries so far."""

    title: str
    entries: list[str] = field(default_factory=list)


@dataclass
class _Reading:
    """The section being read: its heading, its version and date (``None`` for "Nieopublikowane"), the summary's lines
    and its groups so far."""

    heading: str
    numbered: tuple[str, date] | None
    summary: list[str] = field(default_factory=list)
    groups: list[_Group] = field(default_factory=list)

    def finished_groups(self) -> tuple[Group, ...]:
        for group in self.groups:
            if not group.entries:
                raise ChangelogError(f"Grupa „{group.title}” w „{self.heading}” nie ma wpisów.")
        return tuple(Group(group.title, tuple(group.entries)) for group in self.groups)

    def release(self) -> Release:
        assert self.numbered is not None
        version, released = self.numbered
        if not self.groups:
            raise ChangelogError(f"Wersja {version} nie ma wpisów.")
        return Release(version, released, "\n".join(self.summary).strip(), self.finished_groups())


def _reading(heading: str) -> _Reading:
    if heading == UNRELEASED:
        return _Reading(heading, None)
    if (numbered := _VERSION.match(heading)) is None:
        raise ChangelogError(f"Nagłówek „{heading}” nie ma postaci „1.0.0 — 2026-10-19”.")
    try:
        released = date.fromisoformat(numbered["date"])
    except ValueError:
        raise ChangelogError(f"Nagłówek „{heading}” ma błędną datę.") from None
    return _Reading(heading, (numbered["version"], released))


def _sections(lines: Iterable[str]) -> list[_Reading]:
    """The sections under the title, each read whole."""
    sections: list[_Reading] = []
    for line in lines:
        current = sections[-1] if sections else None
        if heading := _RELEASE.match(line):
            sections.append(_reading(heading["heading"]))
        elif group := _GROUP.match(line):
            if current is None:
                raise ChangelogError(f"Grupa „{group['title']}” stoi przed pierwszą wersją.")
            name = group["title"]
            if name not in GROUPS:
                raise ChangelogError(f"Grupa „{name}” nie jest jedną z: {', '.join(GROUPS)}.")
            if current.groups and GROUPS.index(name) <= GROUPS.index(current.groups[-1].title):
                raise ChangelogError(f"Grupy w „{current.heading}” muszą iść w kolejności: {', '.join(GROUPS)}.")
            current.groups.append(_Group(name))
        elif not line.strip():
            continue
        elif current is None:
            raise ChangelogError(f"Tekst „{line.strip()}” stoi przed pierwszą wersją.")
        elif current.groups:
            if (entry := _ENTRY.match(line)) is None:
                raise ChangelogError(f"Wiersz „{line.strip()}” w „{current.heading}” nie jest punktem „- …”.")
            current.groups[-1].entries.append(entry["text"])
        else:
            current.summary.append(line)
    return sections


def parse_changelog(text: str) -> Changelog:
    """The unreleased entries and the versions, which must come newest first, each with an entry."""
    lines = iter(text.splitlines())
    first = next((line for line in lines if line.strip()), "")
    if (title := _TITLE.match(first)) is None or title["title"] != TITLE:
        raise ChangelogError(f"Historia zmian musi zaczynać się nagłówkiem „# {TITLE}”.")
    sections = _sections(lines)
    unreleased: tuple[Group, ...] = ()
    if sections and sections[0].numbered is None:
        unreleased = sections.pop(0).finished_groups()
    if any(section.numbered is None for section in sections):
        raise ChangelogError(f"Sekcja „{UNRELEASED}” może być tylko jedna, na samej górze.")
    releases = [section.release() for section in sections]
    for newer, older in zip(releases, releases[1:], strict=False):
        if version_key(newer.version) <= version_key(older.version):
            raise ChangelogError(f"Wersja {older.version} musi stać nad {newer.version}: od najnowszej.")
    return Changelog(unreleased, tuple(releases))


def is_newer(version: str, than: str | None) -> bool:
    """Whether ``version`` is newer than ``than``; any version is newer than none."""
    return than is None or version_key(version) > version_key(than)


def to_announce(last_seen: str | None, current: str) -> bool:
    """Whether the start of ``current`` opens its "Co nowego": only after an older version was seen; a new User or the
    first start after this change only records it."""
    return last_seen is not None and is_newer(current, last_seen)
