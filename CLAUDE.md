# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

This is a freshly created PyCharm project. The only source file is `main.py`, which is still PyCharm's default sample script. There is no application code, dependency manifest, test suite, linter config, or README yet. The git remote `origin` is https://github.com/Gerruppa/Financial-APP.git, and the default branch is `main`. Update this file as the real architecture of the financial app takes shape.

The app re-implements the inwestomat.eu "Portfolio tracker" Google Sheet. The agreed spec is `docs/spec.md`, the glossary is `CONTEXT.md` and key decisions are in `docs/adr/`. `reference/` holds the user's spreadsheet export and its Apps Script source; it is git-ignored because it contains personal financial data, so never commit it or copy its data into tracked files.

## Environment

- Python 3.14 in a virtualenv at `.venv/` (only `pip` installed, no third-party packages).
- Windows host. Use the venv interpreter directly, without relying on activation:
  - Run: `.venv/Scripts/python.exe main.py`
  - Install a package: `.venv/Scripts/python.exe -m pip install <pkg>`

## Agent skills

### Issue tracker

Issues live in GitHub Issues on Gerruppa/Financial-APP (via the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Default label names: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` plus `docs/adr/` at the repo root. See `docs/agents/domain.md`.
