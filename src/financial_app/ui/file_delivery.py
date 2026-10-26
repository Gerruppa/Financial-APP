"""Hands an exported file to the user and says so. In the browser it is a download; the native window has no download
bar, so the file is saved to the Windows Downloads folder and the notification shows where, with a button that opens
the folder with the file selected."""

import os
import subprocess
from pathlib import Path

from nicegui import app, ui


def is_native() -> bool:
    return app.native.main_window is not None


def downloads_dir() -> Path:
    return Path.home() / "Downloads"


def _free_path(folder: Path, name: str) -> Path:
    """``name`` in ``folder``, or with " (2)", " (3)"... before the extension when it is taken."""
    path = folder / name
    stem, suffix = Path(name).stem, Path(name).suffix
    number = 2
    while path.exists():
        path = folder / f"{stem} ({number}){suffix}"
        number += 1
    return path


def _show_in_folder(path: Path) -> None:
    if os.name == "nt":
        subprocess.Popen(["explorer", f"/select,{path}"])  # noqa: S603, S607 - fixed program, a path we just wrote


def deliver_file(data: bytes, name: str) -> None:
    """Download ``data`` as ``name`` (browser), or save it to Pobrane (native window), and notify the user."""
    if not is_native():
        ui.download(data, name)
        ui.notify(f"Pobrano plik {name}", type="positive")
        return
    folder = downloads_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = _free_path(folder, name)
        path.write_bytes(data)
    except OSError as error:
        ui.notify(f"Nie udało się zapisać pliku {name}: {error}", type="negative")
        return
    _saved_dialog(path)


def _saved_dialog(path: Path) -> None:
    """Says where the file is; opened under the page layout, which outlives the control that was clicked."""
    with ui.context.client.layout, ui.dialog() as dialog, ui.card().mark("file-saved"):
        ui.label("Zapisano plik w folderze Pobrane").classes("text-lg font-bold")
        ui.label(str(path)).classes("k-muted break-all")
        with ui.row().classes("w-full justify-end"):
            ui.button("Pokaż w folderze", on_click=lambda: _show_in_folder(path)).props("outline").mark("file-show")
            ui.button("Zamknij", on_click=dialog.close).props("flat").mark("file-close")
    dialog.on("hide", dialog.delete)
    dialog.open()
