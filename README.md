# Moje inwestycje

A personal investment tracker for Windows, re-implementing the inwestomat.eu "Portfolio tracker" Google Sheet as a local desktop app (NiceGUI in a native window, SQLite). The spec is in `docs/spec.md`.

## Install

Requires Python 3.14.

```
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Desktop shortcut

Create a "Moje inwestycje" shortcut on your desktop:

```
powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1
```

Double-clicking the shortcut opens the app in its own window, with no console. The shortcut points at `.venv\Scripts\financial-app-gui.exe`, so run the script again if you recreate the virtualenv somewhere else. Pass `-Destination <folder>` to put the shortcut somewhere other than the desktop.

From a terminal, you can also start the app with `.venv\Scripts\python.exe main.py`.

## Your data

The database is stored outside the repository, in `%LOCALAPPDATA%\FinancialApp\financial_app.sqlite3`. Set `FINANCIAL_APP_DATA_DIR` to use a different folder.

- **Backups.** Every start copies the database into the `backups` subfolder, before any schema migration runs. Only the newest 30 copies are kept. To restore one, close the app and copy the backup over `financial_app.sqlite3`.
- **Log.** When the app runs without a console (as from the shortcut), its output goes to `financial_app.log` in the same folder. The log is overwritten at each start.
