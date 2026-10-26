"""The update notice under the version label: a few seconds after start KAPITA asks GitHub for the latest Release and,
when it is newer, shows "Dostępna wersja X"; clicking it offers the installation, which downloads the installer,
starts it silently and quits so it can replace the files (the data folder stays)."""

import tempfile
import webbrowser
from pathlib import Path

from nicegui import app, run, ui

from financial_app.domain.app_update import RELEASES_PAGE, LatestRelease, UpdateError, newer_release
from financial_app.sources.app_update import UpdateSource

CHECK_DELAY = 3.0


def update_notice(updates: UpdateSource | None, version: str) -> None:
    """Build the (hidden) notice and schedule the check; nothing happens without ``updates``."""
    if updates is None:
        return
    button = ui.button().props("flat dense no-caps color=warning").classes("text-xs").mark("update-available")
    button.set_visibility(False)

    async def check() -> None:
        try:
            found = await run.io_bound(updates.latest)
        except UpdateError:
            # Offline or a broken answer must never nag; the next start asks again
            return
        latest = newer_release(found, version) if found is not None else None
        if latest is None:
            return
        button.set_text(f"Dostępna wersja {latest.version}")
        button.on_click(lambda: _open_dialog(updates, latest))
        button.set_visibility(True)
        ui.notify(f"Dostępna nowa wersja KAPITA: {latest.version}", type="info")

    ui.timer(CHECK_DELAY, check, once=True)


def _open_dialog(updates: UpdateSource, latest: LatestRelease) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-[28rem] max-w-full").mark("update-dialog"):
        ui.label(f"Dostępna wersja {latest.version}").classes("text-lg font-bold")
        if updates.can_install:
            ui.label(
                "KAPITA pobierze instalator, zamknie się, zaktualizuje i uruchomi ponownie. Twoje dane zostają."
            ).classes("text-sm")
        else:
            ui.label("Tej wersji aplikacji nie zaktualizuje instalator; pobierz nową ze strony wydań.").classes(
                "text-sm"
            )
        status = ui.label().classes("text-sm k-muted").mark("update-status")
        with ui.row().classes("w-full justify-end"):
            ui.button("Później", on_click=dialog.close).props("flat").mark("update-later")
            ui.button("Strona wydań", on_click=lambda: webbrowser.open(RELEASES_PAGE)).props("outline").mark(
                "update-page"
            )
            if updates.can_install:
                install = ui.button("Zainstaluj teraz").mark("update-install")
                install.on_click(lambda: _install(updates, latest, install, status))
    dialog.on("hide", dialog.delete)
    dialog.open()


async def _install(updates: UpdateSource, latest: LatestRelease, button: ui.button, status: ui.label) -> None:
    button.disable()
    status.set_text("Pobieranie instalatora…")
    try:
        folder = Path(tempfile.mkdtemp(prefix="kapita-update-"))
        installer = await run.io_bound(updates.download, latest, folder)
        if installer is None:
            return
        updates.install(installer)
    except (UpdateError, OSError) as error:
        status.set_text(str(error))
        button.enable()
        return
    status.set_text("Uruchamianie instalatora…")
    app.shutdown()
