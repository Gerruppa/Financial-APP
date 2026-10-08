# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Stage 0 skeleton (issue #8). The git remote `origin` is https://github.com/Gerruppa/Financial-APP.git, and the default branch is `main`. Update this file as the architecture grows.

Layout (`src/financial_app/`, see ADR-0001):
- `domain/`: pure-Python calculations. It must never import NiceGUI, SQLAlchemy, Alembic or pywebview; `tests/test_architecture.py` enforces this. `domain/formatting.py` is the single Polish number formatter (`format_pln`, `format_percent`); use it for every amount shown in the UI.
- `persistence/`: SQLite through SQLAlchemy. `models.py` holds the ORM models, `migrations/` holds Alembic revisions, and `db.init_db(path)` applies them at start-up, right after `backup.backup_database` copies the file into `paths.backups_dir()` (newest 30 kept). The database lives in the user's app-data folder (`paths.data_dir()`, overridable with `FINANCIAL_APP_DATA_DIR`), never in the repo. Change the schema only through a new migration: `.venv/Scripts/python.exe -m alembic revision --autogenerate -m "..."`. `tests/test_database.py` fails if the models and migrations drift apart.
- `ui/shell.py`: the NiceGUI window (left menu, header with the View Scope switcher, "+" transaction button). Tabs are `ui.sub_pages` routes.
- `app.py`: entry point, also used by `main.py` and by the console-less `financial-app-gui.exe` that the desktop shortcut starts (`scripts/create_desktop_shortcut.ps1`). Without a console, stdout/stderr go to `paths.log_path()`.

The app re-implements the inwestomat.eu "Portfolio tracker" Google Sheet. The agreed spec is `docs/spec.md`, the glossary is `CONTEXT.md` and key decisions are in `docs/adr/`. `reference/` holds the user's spreadsheet export and its Apps Script source; it is git-ignored because it contains personal financial data, so never commit it or copy its data into tracked files.

## Environment

- Python 3.14 in a virtualenv at `.venv/`. Dependencies are listed in `pyproject.toml`; the package is installed in editable mode with `.venv/Scripts/python.exe -m pip install -e ".[dev]"`.
- Windows host. Use the venv interpreter directly, without relying on activation:
  - Run the app (native window): `.venv/Scripts/python.exe main.py`
  - Tests: `.venv/Scripts/python.exe -m pytest` (UI tests use NiceGUI's `user_simulation`, with no browser)
  - Type check: `.venv/Scripts/python.exe -m mypy` (strict)
  - Lint and format: `.venv/Scripts/python.exe -m ruff check .` and `.venv/Scripts/python.exe -m ruff format .`

## Agent skills

### Issue tracker

Issues live in GitHub Issues on Gerruppa/Financial-APP (via the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Default label names: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` plus `docs/adr/` at the repo root. See `docs/agents/domain.md`.
