"""The changelog (issue #200): its Markdown read into Releases, and the one announced on a new version's first start."""

from datetime import date

import pytest

from financial_app.domain.changelog import ChangelogError, parse_changelog, to_announce

SAMPLE = """\
# Historia zmian

## Nieopublikowane

### Poprawki
- Poprawiono kolor pola Konto.

## 1.1.0 — 2026-11-02

### Nowe funkcje
- Wyszukiwarka w nagłówku.
- Motyw Golden.

### Zmiany
- Przycisk „+” nie jest pokazywany na Dashboardzie.

## 1.0.0 — 2026-10-19

Pierwsze wydanie.

### Nowe funkcje
- Transakcje i Portfolio.
"""


def test_reads_released_versions_newest_first_with_their_groups() -> None:
    changelog = parse_changelog(SAMPLE)

    newest, first = changelog.releases
    assert (newest.version, newest.released) == ("1.1.0", date(2026, 11, 2))
    assert [(group.title, group.entries) for group in newest.groups] == [
        ("Nowe funkcje", ("Wyszukiwarka w nagłówku.", "Motyw Golden.")),
        ("Zmiany", ("Przycisk „+” nie jest pokazywany na Dashboardzie.",)),
    ]
    assert (first.version, first.summary) == ("1.0.0", "Pierwsze wydanie.")
    assert newest.summary == ""


def test_keeps_the_unreleased_entries_apart() -> None:
    changelog = parse_changelog(SAMPLE)

    assert [(group.title, group.entries) for group in changelog.unreleased] == [
        ("Poprawki", ("Poprawiono kolor pola Konto.",))
    ]
    assert changelog.release("1.0.0") is changelog.releases[1]
    assert changelog.release("2.0.0") is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("## 1.0.0 — 2026-10-19\n\n### Nowe funkcje\n- A.\n", "Historia zmian"),
        ("# Historia zmian\n\n## 1.0 z października\n\n### Poprawki\n- A.\n", "1.0 z października"),
        ("# Historia zmian\n\n## 1.0.0 — 2026-10-19\n\n### Inne\n- A.\n", "Inne"),
        ("# Historia zmian\n\n## 1.0.0 — 2026-10-19\n\n### Poprawki\n- A.\n\n### Nowe funkcje\n- B.\n", "kolejności"),
        ("# Historia zmian\n\n## 1.0.0 — 2026-10-19\n\n### Poprawki\n\n", "Poprawki"),
        ("# Historia zmian\n\n## 1.0.0 — 2026-10-19\n\n", "1.0.0"),
        (
            "# Historia zmian\n\n## 1.0.0 — 2026-10-19\n\n### Poprawki\n- A.\n\n"
            "## 1.1.0 — 2026-11-02\n\n### Poprawki\n- B.\n",
            "1.1.0",
        ),
        ("# Historia zmian\n\n## 1.0.0 — 2026-10-19\n\n### Poprawki\nTekst bez punktu.\n", "Tekst bez punktu."),
        ("# Historia zmian\n\n## 1.0.0 — 2026-13-01\n\n### Poprawki\n- A.\n", "błędną datę"),
        ("# Historia zmian\n\nWstęp.\n\n## 1.0.0 — 2026-10-19\n\n### Poprawki\n- A.\n", "Wstęp."),
        ("# Historia zmian\n\n## 1.0.0 — 2026-10-19\n\n### Poprawki\n- A.\n\n## Nieopublikowane\n", "na samej górze"),
        ("# Historia zmian\n\n## Nieopublikowane\n\n## Nieopublikowane\n", "na samej górze"),
    ],
)
def test_rejects_a_broken_changelog_naming_the_entry(text: str, message: str) -> None:
    with pytest.raises(ChangelogError, match=message):
        parse_changelog(text)


@pytest.mark.parametrize(
    ("last_seen", "current", "announced"),
    [
        (None, "1.1.0", False),
        ("1.1.0", "1.1.0", False),
        ("1.0.0", "1.1.0", True),
        ("1.2.0", "1.1.0", False),
    ],
)
def test_announces_only_a_version_newer_than_the_last_seen(
    last_seen: str | None, current: str, announced: bool
) -> None:
    assert to_announce(last_seen, current) is announced
