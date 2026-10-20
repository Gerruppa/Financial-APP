"""The changelog (issue #200): the version under the logo opens every released version, and the first start of a new
version opens "Co nowego" with only that version.

The text lives in ``changelog.md`` beside this module (format in ``domain/changelog.py``), kept by hand: a PR adds an
entry to its "Nieopublikowane" section, which the window never shows.
"""

from collections.abc import Iterable
from importlib.resources import files

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.changelog import (
    TITLE,
    Changelog,
    ChangelogError,
    Release,
    is_newer,
    parse_changelog,
    to_announce,
)
from financial_app.domain.formatting import format_date
from financial_app.persistence.settings import LAST_SEEN_VERSION, load_setting, save_setting


def load_changelog() -> Changelog:
    """The changelog shipped with the app."""
    return parse_changelog(files(__package__).joinpath("changelog.md").read_text(encoding="utf-8"))


def open_changelog(title: str, releases: Iterable[Release]) -> None:
    """A scrolling dialog of ``releases``, newest first; open it from an element that outlives it."""
    with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full").mark("changelog"):
        ui.label(title).classes("text-lg font-bold")
        with ui.scroll_area().classes("w-full h-[60vh]"):
            for release in releases:
                ui.label(f"{release.version} — {format_date(release.released)}").classes("text-base font-bold pt-2")
                if release.summary:
                    ui.markdown(release.summary).classes("text-sm")
                for group in release.groups:
                    ui.label(group.title).classes("text-sm font-medium pt-1")
                    ui.markdown("\n".join(f"- {entry}" for entry in group.entries)).classes("text-sm")
        with ui.row().classes("w-full justify-end"):
            ui.button("Zamknij", on_click=dialog.close).props("flat")
    dialog.on("hide", dialog.delete)
    dialog.open()


def version_label(version: str) -> None:
    """The version under the logo; clicking it opens the history of changes."""
    label = ui.label(version).classes("text-xs opacity-60 cursor-pointer").mark("app-version")
    label.tooltip(TITLE)
    label.on("click", _open_history)


def _open_history() -> None:
    try:
        releases = load_changelog().releases
    except ChangelogError as error:
        ui.notify(f"Nie można odczytać historii zmian: {error}", type="negative")
        return
    open_changelog(TITLE, releases)


def announce_new_version(engine: Engine, version: str) -> None:
    """On the first start of ``version`` after an older one, open "Co nowego" with it, and record it as seen; going
    back to an older version records nothing, so the newer one is not announced twice."""
    last_seen = load_setting(engine, LAST_SEEN_VERSION)
    if not is_newer(version, last_seen):
        return
    save_setting(engine, LAST_SEEN_VERSION, version)
    if not to_announce(last_seen, version):
        return
    try:
        release = load_changelog().release(version)
    except ChangelogError:
        # A broken file never stops the start; clicking the version says what is wrong
        return
    if release is not None:
        open_changelog("Co nowego", [release])
