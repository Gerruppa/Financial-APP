# KAPITA

A personal investment tracker for Windows, re-implementing the inwestomat.eu "Portfolio tracker" Google Sheet as a local desktop app (NiceGUI in a native window, SQLite). The spec is in `docs/spec.md`.

## Install from the installer

Run `KAPITA-1.0.0-setup.exe`. It installs for the current user only (no administrator rights) into `%LOCALAPPDATA%\Programs\KAPITA`, adds KAPITA to the Start menu and, if you tick it, to the desktop. Installing a newer version over it upgrades in place; uninstalling (Settings > Apps) leaves your data alone. KAPITA needs the Microsoft Edge WebView2 runtime, which Windows 11 already has.

## Build the installer

Needs Inno Setup 6 (`winget install JRSoftware.InnoSetup`) and the `build` extra:

```
.venv\Scripts\python.exe -m pip install -e ".[dev,build]"
powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1
```

The installer lands in `dist\KAPITA-<version>-setup.exe`; the version comes from `src/financial_app/__init__.py`. To change the icons, replace `packaging/kapita-logo.png` and run `.venv\Scripts\python.exe scripts\make_icons.py`.

## Install for development

Requires Python 3.14.

```
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Desktop shortcut

Create a "KAPITA" shortcut on your desktop that starts the development copy:

```
powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1
```

Double-clicking the shortcut opens the app in its own window, with no console. The shortcut points at `.venv\Scripts\kapita-gui.exe`, so run the script again if you recreate the virtualenv somewhere else. Pass `-Destination <folder>` to put the shortcut somewhere other than the desktop.

From a terminal, you can also start the app with `.venv\Scripts\python.exe main.py`.

## Your data

The database is stored outside the repository, in `%LOCALAPPDATA%\KAPITA\financial_app.sqlite3`; the installed app and the development copy share it. Set `FINANCIAL_APP_DATA_DIR` to use a different folder. Before 1.0 the folder was `%LOCALAPPDATA%\FinancialApp`: the first start of KAPITA moves it to the new name, as long as no `KAPITA` folder exists yet.

- **Backups.** Every start copies the database into the `backups` subfolder, before any schema migration runs. Only the newest 30 copies are kept. To restore one, close the app and copy the backup over `financial_app.sqlite3`.
- **Log.** When the app runs without a console (as from the shortcut), its output goes to `financial_app.log` in the same folder. The log is overwritten at each start.
