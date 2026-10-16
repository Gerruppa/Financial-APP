# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Stages 1 (transactions and Portfolio), 2 (automatic prices), 3 (Polish treasury bonds), 4 (Dashboard, History, Results) and 5 (reports: Benchmarks, Sell Summary, passive-income calendar) are done; Stage 6 (#7) has started (L-17 XTB import and Reconciliation, L-27 Transakcje filters). Open work is in GitHub Issues (Stage 6: #94–#100). The git remote `origin` is https://github.com/Gerruppa/Financial-APP.git, the default branch `main`; work goes on a feature branch and a PR.

## Layout

`src/financial_app/` in four layers (ADR-0001): `domain/` (pure-Python calculations), `persistence/` (SQLite through SQLAlchemy), `sources/` (Price Sources, importers and services above persistence) and `ui/` (NiceGUI). **Before changing a module, read its entry in `docs/architecture.md`**: the main functions, UI markers and decisions per module. Update that entry when you change the module. `FILETREE.md` finds a file by purpose.

Rules no config enforces:
- `domain/` never imports NiceGUI, SQLAlchemy, Alembic or pywebview (`tests/test_architecture.py` checks).
- Every amount or date shown in or read from the UI goes through `domain/formatting.py` (`format_pln`, `format_percent`, `format_date`, `parse_number`, `parse_date`, ...).
- One FIFO engine: `domain/lots.py` (ADR-0003); Positions, realised results and Sale Pairs all come from its replay.
- The schema changes only through a new migration: `.venv/Scripts/python.exe -m alembic revision --autogenerate -m "..."`; `tests/test_database.py` fails if models and migrations drift. The database lives in the user's app-data folder (`FINANCIAL_APP_DATA_DIR` overrides), never in the repo.
- UI text is Polish; code, DB names and docs English. Errors for the user carry a Polish message.
- UI tests use NiceGUI's `user_simulation` and find elements by `.mark(...)` markers; `user.find("text")` matches substrings, so keep labels and markers unique.
- Each tab redraws through its page's `refresh()`; `ui/shell.py` calls it after a save, a price refresh, a scope change and once History is computed.

The app re-implements the inwestomat.eu "Portfolio tracker" Google Sheet. The agreed spec is `docs/spec.md`, the glossary is `CONTEXT.md` (its Polish-to-English index is `GLOSSARY.md`, kept in step by `tests/test_glossary.py`) and key decisions are in `docs/adr/`. `reference/` holds the user's spreadsheet export and its Apps Script source; it is git-ignored because it contains personal financial data, so never commit it or copy its data into tracked files.

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

`docs/backlog.md` is the former local backlog (`L-n` ids, done per stage); new work goes to GitHub Issues.

### Triage labels

Default label names: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` plus `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## FILETREE.md

`FILETREE.md` indexes every file with a one-line role summary, grouped by
directory. Read it to find code by purpose before `ls`/`grep`/`find`: it
turns "search the repo" into "look it up". Auto-maintained; don't hand-edit.

```
## (root)/

- `main.py`: Entry point that starts the app in a native window

## src/financial_app/domain/

- `lots.py`: FIFO engine; builds open Positions and Lots from Transactions
- `formatting.py`: Polish number and date formatting and parsing
```
