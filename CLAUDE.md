# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

The app is called KAPITA; version 1.0.0 (`financial_app.__version__`) ships as a Windows installer built by `scripts/build_installer.ps1` (#99). Stages 1 (transactions and Portfolio), 2 (automatic prices), 3 (Polish treasury bonds), 4 (Dashboard, History, Results) and 5 (reports: Benchmarks, Sell Summary, passive-income calendar) are done; Stage 6 (#7) is nearly done (L-17 XTB import and Reconciliation, L-27 Transakcje filters, #95 Contribution Limits, #99 installer). Open work is in GitHub Issues (Stage 6: #94–#100). The git remote `origin` is https://github.com/Gerruppa/Financial-APP.git, the default branch `main`; work goes on a feature branch and a PR.

## Layout

`src/financial_app/` in four layers (ADR-0001): `domain/` (pure-Python calculations), `persistence/` (SQLite through SQLAlchemy), `sources/` (Price Sources, importers and services above persistence) and `ui/` (NiceGUI). **Before changing a module, read its entries in `docs/architecture/`**: the main functions, UI markers and decisions per module; `grep -l "<module path>" docs/architecture/` finds them, and `docs/architecture.md` is the index. Update those entries when you change the module. `FILETREE.md` finds a file by purpose.

Rules no config enforces:
- `domain/` never imports NiceGUI, SQLAlchemy, Alembic or pywebview (`tests/test_architecture.py` checks).
- Every amount or date shown in or read from the UI goes through `domain/formatting.py` (`format_pln`, `format_percent`, `format_date`, `parse_number`, `parse_date`, ...).
- One FIFO engine: `domain/lots.py` (ADR-0003); Positions, realised results and Sale Pairs all come from its replay.
- The schema changes only through a new migration: `.venv/Scripts/python.exe scripts/new_migration.py "..."` (numbers it, autogenerates it on a scratch database, runs ruff); then write its docstring; `tests/test_database.py` fails if models and migrations drift. The database lives in the user's app-data folder (`FINANCIAL_APP_DATA_DIR` overrides), never in the repo.
- UI text is Polish; code, DB names and docs English. Errors for the user carry a Polish message.
- UI tests use NiceGUI's `user_simulation` and find elements by `.mark(...)` markers; `user.find("text")` matches substrings, so keep labels and markers unique.
- Each tab redraws through its page's `refresh()`, on the changes its class declares in `CHANGES` (`ui/changes.py`); `ui/shell.py` only publishes the changes (a save, a price or bond data refresh, a scope switch, an Instrument change, History outdated or computed). A new tab declares `CHANGES` and joins the shell's `tabs` list.
- Open a `ui.dialog` from an element that outlives it (e.g. `with self.box:` in `ui/header_search.py`): NiceGUI deletes a dialog once the element it was opened in is redrawn away and collected, such as a row of a refreshable list.

The app re-implements the inwestomat.eu "Portfolio tracker" Google Sheet. The agreed spec is `docs/spec.md`, the glossary is `CONTEXT.md` (its Polish-to-English index is `GLOSSARY.md`, kept in step by `tests/test_glossary.py`) and key decisions are in `docs/adr/`. `reference/` holds the user's spreadsheet export and its Apps Script source; it is git-ignored because it contains personal financial data, so never commit it or copy its data into tracked files.

## Environment

- Python 3.14 in a virtualenv at `.venv/`. Dependencies are listed in `pyproject.toml`; the package is installed in editable mode with `.venv/Scripts/python.exe -m pip install -e ".[dev]"`.
- Windows host. Use the venv interpreter directly, without relying on activation:
  - Run the app (native window): `.venv/Scripts/python.exe main.py`; `--browser` serves it on http://127.0.0.1:8080 instead, `--demo` does that on a fresh made-up database in TEMP. For a visual change, screenshot the tabs before and after with the `kapita-screenshot` skill (`scripts/screenshot.py`).
  - While working, run the test files of the changed modules by path (`.venv/Scripts/python.exe -m pytest tests/test_<module>.py`, seconds); a change to a central module makes the Delta tests near the full suite.
  - Delta tests, once before each commit: `.venv/Scripts/python.exe -m pytest --testmon -n auto` (pytest-testmon runs only the tests whose covered code changed; its first run, or a run after a dependency or `conftest.py` change, is the full suite). Testmon tracks only Python, so after changing a non-Python file a test reads (`tests/fixtures/`, `docs/`, `CONTEXT.md`, `GLOSSARY.md`) also run that test by path.
  - Regression tests, the full suite: `.venv/Scripts/python.exe -m pytest -n auto` (about 2.5 minutes; UI tests use NiceGUI's `user_simulation`, with no browser). Run it only when asked or when a milestone closes; CI (`.github/workflows/ci.yml`) runs it on a milestone's closing, a `v*` tag and by hand (`gh workflow run CI`), not on PRs.
  - Without the UI tests: add `-m "not ui"` to either command.
  - Type check: `.venv/Scripts/python.exe -m mypy` (strict)
  - Lint and format: `.venv/Scripts/python.exe -m ruff check .` and `.venv/Scripts/python.exe -m ruff format .`
- Change source files with the Edit tool, one call per replacement; Python heredocs piped through Git Bash break on quotes.
- To merge a PR, run `gh pr merge <n> --merge --delete-branch` as a command of its own: only that exact form matches the allow rule in `.claude/settings.json`.
- A small task (one PR, no spec or migration: a visual tweak, a label, a doc fix) needs no issue and no triage: branch, change, Delta tests, PR, then merge it without asking once pre-commit and the Delta tests pass. Ask before merging anything larger, a migration or a change to `domain/lots.py`.
- Review the uncommitted diff (`git diff main`) before the first commit, apply the fixes, then commit once.
- Changelog (`src/financial_app/ui/changelog.md`, Polish): a PR that changes what the user sees or gets (a new feature, a fixed bug, a changed behaviour) adds one sentence to its "Nieopublikowane" section, under Nowe funkcje, Poprawki or Zmiany, without issue numbers; a refactor, optimisation, architecture, tests, docs or tooling gets none. A release renames the section to "1.1.0 — <date>" as `__version__` changes (`tests/test_changelog_ui.py` checks the section exists), and the GitHub Release takes the same text.

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
turns "search the repo" into "look it up". Refresh it once per PR: run
`/filetree:update` before opening the PR and commit `FILETREE.md` and
`FILETREE.hash.json` with it; don't hand-edit.

```
## (root)/

- `main.py`: Entry point that starts the app in a native window

## src/financial_app/domain/

- `lots.py`: FIFO engine; builds open Positions and Lots from Transactions
- `formatting.py`: Polish number and date formatting and parsing
```
