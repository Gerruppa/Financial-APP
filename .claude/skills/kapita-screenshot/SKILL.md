---
name: kapita-screenshot
description: Screenshot KAPITA's tabs on made-up demo data. Use for any visual change (layout, styling, a new UI element) to see the tab before and after, to confirm a change in the real app rather than only in tests, or when the user asks to run, see or screenshot the app.
---

# KAPITA screenshots

The app opens a native pywebview window you cannot see. `main.py --demo` serves the same UI in a browser, on a fresh database of made-up data in `%TEMP%\KAPITA-demo`; the user's real data is never read or touched. `scripts/screenshot.py` wraps it into one command.

## Shoot

```bash
.venv/Scripts/python.exe scripts/screenshot.py dashboard portfolio --out "<scratchpad>/shots/before"
```

- A tab is its route without the slash: `dashboard` (`/`), `portfolio`, `transakcje`, `obligacje`, `ustawienia`, `benchmarki`, `sprzedaz`, `strategie`, `dochod-pasywny`, `multi-asset`. Git Bash turns a leading `/` into a Windows path, so never pass one.
- `--width` / `--height` set the viewport (default 1400x900, the native window); `--theme golden` shoots the dark Golden Theme, so check a colour change in both.
- It prints each PNG's path; `Read` the PNG to look at it.
- Write the shots to the session scratchpad, never into the repo.

## A visual change

1. Before editing, shoot the tabs the change touches into `shots/before`.
2. Make the change; run the Delta tests.
3. Shoot the same tabs into `shots/after`, `Read` both and compare them. Iterate until the after shot shows what was asked.
4. Show the user the after shot (its full path), and describe the before/after difference in the PR's Evidence section.

## Limits

- The demo has only PLN Accounts and Manual Prices and skips the refresh at start: no network, no quotes, no History, so Wpłaty netto and XIRR show "—". To show other data (bonds, foreign currency, more Transactions), extend `src/financial_app/sources/demo_data.py` `seed_demo_data` with made-up data only; its tests are `tests/test_demo_data.py`.
- A dialog, a hover or a click-revealed state needs interaction the headless shot cannot do; check those with a `user_simulation` test instead.
- To look by hand: `.venv/Scripts/python.exe main.py --demo` and open http://127.0.0.1:8080; `main.py --browser` serves the user's real data the same way.
