"""scripts/release.py's text edits: the version bump, the changelog's numbered section and the GitHub Release text."""

import importlib.util
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

from financial_app.domain.changelog import ChangelogError, parse_changelog


def _load() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "release.py"
    spec = importlib.util.spec_from_file_location("release", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = _load()

INIT = '"""KAPITA."""\n\n# The one version number\n__version__ = "1.4.2"\n'
CHANGELOG = """# Historia zmian

## Nieopublikowane

### Nowe funkcje
- Nowa rzecz.

### Poprawki
- Poprawiona rzecz.

## 1.4.2 — 2026-10-31

### Zmiany
- Starsza zmiana.
"""


def test_the_version_bump_changes_only_the_version_line() -> None:
    assert release.bump_version(INIT, "1.5.0") == INIT.replace("1.4.2", "1.5.0")


@pytest.mark.parametrize("version", ["1.4.2", "1.4.1", "1.5", "v1.5.0"])
def test_a_version_not_newer_or_not_x_y_z_is_refused(version: str) -> None:
    with pytest.raises(ValueError, match=version.replace(".", r"\.")):
        release.bump_version(INIT, version)


def test_the_unreleased_section_gets_the_version_and_the_day() -> None:
    released = release.release_changelog(CHANGELOG, "1.5.0", date(2026, 11, 2))

    assert released == CHANGELOG.replace("## Nieopublikowane", "## 1.5.0 — 2026-11-02")
    assert [r.version for r in parse_changelog(released).releases] == ["1.5.0", "1.4.2"]


def test_a_release_with_nothing_unreleased_is_refused() -> None:
    empty = "# Historia zmian\n\n## 1.4.2 — 2026-10-31\n\n### Zmiany\n- Starsza zmiana.\n"

    with pytest.raises(ChangelogError, match="Nieopublikowane"):
        release.release_changelog(empty, "1.5.0", date(2026, 11, 2))


def test_the_release_notes_say_how_to_install_then_list_the_version_s_changes() -> None:
    released = release.release_changelog(CHANGELOG, "1.5.0", date(2026, 11, 2))

    assert release.release_notes(released, "1.5.0") == (
        "Aktualizacja aplikacji **KAPITA** do wersji 1.5.0.\n"
        "\n"
        "## Instalacja\n"
        "\n"
        "Pobierz `KAPITA-1.5.0-setup.exe` i uruchom. Instalator zaktualizuje zainstalowaną wersję, a Twoje dane w "
        "`%LOCALAPPDATA%\\KAPITA` zostają.\n"
        "\n"
        "## Zmiany\n"
        "\n"
        "### Nowe funkcje\n"
        "- Nowa rzecz.\n"
        "\n"
        "### Poprawki\n"
        "- Poprawiona rzecz.\n"
    )


def test_notes_for_a_version_missing_from_the_changelog_are_refused() -> None:
    with pytest.raises(ChangelogError, match="1.9.9"):
        release.release_notes(CHANGELOG, "1.9.9")
