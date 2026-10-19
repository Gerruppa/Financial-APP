# Project Filetree

_Auto-maintained by `/filetree:update`. Content hashes live in the sidecar `FILETREE.hash.json`; do not edit it by hand._

## (root)/

- `.filetree.json`: Filetree manifest config: manifest path, include/exclude filters, summary language, commit guard and self-only mode.
- `.gitignore`: Git ignore rules for the venv, caches, build output, the personal spreadsheet reference folder and graphify output.
- `.pre-commit-config.yaml`: Pre-commit hooks: ruff check, ruff format and mypy from the venv.
- `CLAUDE.md`: Guidance for Claude Code: project state, layers and unwritten rules, pointers to docs/architecture/, environment commands.
- `CONTEXT.md`: Domain glossary defining the app's Polish-labelled terms (Accounts, Instruments, Transactions, Lots, Quotes) and terms to avoid.
- `GLOSSARY.md`: Polish-to-English index of glossary terms, mapping UI labels to CONTEXT.md definitions and sections
- `README.md`: User-facing setup guide: install steps, desktop shortcut creation, data location, backups and log file.
- `alembic.ini`: Alembic CLI configuration pointing migrations at the persistence package, with ruff post-write hooks for new revisions; the app runs migrations itself at start-up.
- `main.py`: Convenience script entry point that calls the app's main function to start the window.
- `pyproject.toml`: Package metadata, dependencies, console and GUI entry points, pytest, mypy and ruff settings.

## .claude/skills/kapita-screenshot/

- `SKILL.md`: Project skill for screenshotting KAPITA's tabs on made-up demo data before and after a visual change

## .github/workflows/

- `ci.yml`: GitHub Actions job on Windows running ruff, format check, mypy and the full pytest suite on milestone close, v* tags or manual dispatch.

## docs/

- `architecture.md`: Index of the per-module architecture entries in docs/architecture/, plus the domain and persistence layer rules.
- `backlog.md`: Local stand-in for GitHub Issues: done and open stage items, with L-n ids for items not yet on GitHub
- `spec.md`: Agreed product specification: goals, architecture, data model, transaction rules, valuation and feature scope.

## docs/adr/

- `0001-local-nicegui-sqlite-with-pure-domain-core.md`: ADR choosing a local NiceGUI and SQLite app with a UI-independent pure-Python domain core.
- `0002-history-recomputed-not-snapshotted.md`: ADR deciding portfolio history is recomputed from Transactions and cached prices, not stored as daily snapshots.
- `0003-single-fifo-engine-with-actual-and-tax-cost.md`: ADR for one FIFO lot engine carrying Actual and Tax costs per Lot, with FX cash held as Lots.
- `0004-fix-spreadsheet-bugs-document-deviations.md`: ADR to fix known spreadsheet bugs rather than replicate them, recording each number-changing fix as a documented deviation.
- `0005-structured-price-sources-only.md`: ADR restricting automatic prices to structured sources, with MF data authoritative for retail bonds.
- `0006-history-quote-sources-and-split-unadjusting.md`: ADR: History takes Yahoo then Stooq daily quotes and un-adjusts prices for recorded Splits
- `0007-bond-redemption-picks-its-lot.md`: ADR: early bond redemption names its Lot instead of FIFO, other Instruments keep FIFO
- `0008-valuation-snapshots-are-stored.md`: ADR explaining why Dashboard Valuation Snapshots are stored, unlike the recomputed History, and the trade-offs
- `0009-cloud-vps-behind-cloudflare-access.md`: ADR moving the single-user app to an EU VPS behind Cloudflare Tunnel and Access, with the cloud copy as the only data

## docs/agents/

- `domain.md`: Agent instructions for reading CONTEXT.md and ADRs before exploring code and using the glossary's vocabulary.
- `issue-tracker.md`: Agent instructions for managing issues, PRs and wayfinder maps on GitHub with the gh CLI.
- `triage-labels.md`: Mapping of the five canonical triage roles to this repo's GitHub issue label names.

## docs/architecture/

- `accounts.md`: Architecture entry for domain/accounts.py: main functions, UI markers and decisions.
- `analizy.md`: Architecture entry for sources/analizy.py: main functions, UI markers and decisions.
- `app.md`: Architecture entry for app.py: main functions, UI markers and decisions.
- `benchmarks.md`: Architecture entry for Benchmarks (#91, spec 6.2): main functions, UI markers and decisions.
- `bond-calendar.md`: Architecture entry for Bond calendar (L-9, spec 3.4.1): main functions, UI markers and decisions.
- `bond-data.md`: Architecture entry for Bond data (Stage 3, L-1, spec 3.4.1): main functions, UI markers and decisions.
- `bond-drafts.md`: Architecture entry for Maturity and Rollover Drafts (L-6, spec 3.4.1): main functions, UI markers and decisions.
- `bond-series.md`: Architecture entry for Bond Series (L-2, spec 3.4.1): main functions, UI markers and decisions.
- `bossa.md`: Architecture entry for sources/bossa.py: main functions, UI markers and decisions.
- `catalyst-bonds.md`: Architecture entry for Catalyst bonds (L-23, L-24, spec 4.2): main functions, UI markers and decisions.
- `changes.md`: Architecture entry for ui/changes.py (#112): main functions, UI markers and decisions.
- `contribution-limits.md`: Architecture entry for Contribution Limits (#95, spec 8.1): main functions, UI markers and decisions.
- `dashboard-charts.md`: Architecture entry for Dashboard charts (#73, spec 6.1): main functions, UI markers and decisions.
- `dashboard.md`: Architecture entry for Dashboard (#72, spec 5 and 6.1): main functions, UI markers and decisions.
- `demo-mode.md`: Architecture entry for browser and demo mode (--browser, --demo), the demo data seed and the screenshot script
- `early-redemption.md`: Architecture entry for Early Redemption (L-5, spec 3.4.1, ADR-0007): main functions, UI markers and decisions.
- `edo-valuation.md`: Architecture entry for EDO valuation (L-3, spec 3.4.1): main functions, UI markers and decisions.
- `export.md`: Architecture entry for Export: main functions, UI markers and decisions.
- `help-faq.md`: Architecture entry for Pomoc / FAQ (#156): main functions, UI markers and decisions.
- `history-parity-test.md`: Architecture entry for tests/test_history_parity.py (#70, spec 6.1): main functions, UI markers and decisions.
- `info-icons.md`: Architecture entry for Info icons and waterfall amounts: main functions, UI markers and decisions.
- `instrument-search.md`: Architecture entry for domain/instrument_search.py: main functions, UI markers and decisions.
- `instruments.md`: Architecture entry for domain/instruments.py: main functions, UI markers and decisions.
- `investment-goal.md`: Architecture entry for Investment Goal (#96): main functions, UI markers and decisions.
- `investment-strategies.md`: Architecture entry for Investment Strategies (#76, spec 5 and 6.1): main functions, UI markers and decisions.
- `lots.md`: Architecture entry for domain/lots.py: main functions, UI markers and decisions.
- `metrics.md`: Architecture entry for domain/metrics.py (#69, spec 6.1): main functions, UI markers and decisions.
- `multi-asset.md`: Architecture entry for Multi-asset (#75, spec 6.1): main functions, UI markers and decisions.
- `nbp-rates.md`: Architecture entry for sources/nbp.py: main functions, UI markers and decisions.
- `obligacje-tab.md`: Architecture entry for Obligacje tab and Net Value (L-4, spec 3.4.1): main functions, UI markers and decisions.
- `passive-income.md`: Architecture entry for Passive-income calendar (#93, spec 6.2): main functions, UI markers and decisions.
- `portfolio-history.md`: Architecture entry for domain/portfolio_history.py (#68, spec 6.1, ADR-0006): main functions, UI markers and decisions.
- `price-refresh.md`: Architecture entry for sources/prices.py: main functions, UI markers and decisions.
- `prices.md`: Architecture entry for domain/prices.py: main functions, UI markers and decisions.
- `real-return.md`: Architecture entry for Real return (L-10, spec 3.4.1): main functions, UI markers and decisions.
- `recurring-rules.md`: Architecture entry for Recurring Rules (#97, spec 3.3.1): main functions, UI markers and decisions.
- `reset.md`: Architecture entry for persistence/reset.py: main functions, UI markers and decisions.
- `sell-summary.md`: Architecture entry for Sell Summary (#92, spec 6.2): main functions, UI markers and decisions.
- `shell.md`: Architecture entry for ui/shell.py: main functions, UI markers and decisions.
- `spreadsheet-import.md`: Architecture entry for domain/spreadsheet_import.py: main functions, UI markers and decisions.
- `spreadsheet-workbook.md`: Architecture entry for sources/spreadsheet.py: main functions, UI markers and decisions.
- `stooq-price-history.md`: Architecture entry for sources/stooq.py: main functions, UI markers and decisions.
- `term-deposits.md`: Architecture entry for Term Deposits (#160, spec 3.3.2): main functions, UI markers and decisions.
- `todays-view.md`: Architecture entry for Today's View state (#109): main functions, UI markers and decisions.
- `transaction-filters.md`: Architecture entry for Transakcje filters and sorting (L-27): main functions, UI markers and decisions.
- `transaction-form.md`: Architecture entry for Transaction form (#111): main functions, UI markers and decisions.
- `transaction-saving.md`: Architecture entry for Saving Transactions (#110): main functions, UI markers and decisions.
- `transactions.md`: Architecture entry for domain/transactions.py: main functions, UI markers and decisions.
- `treemap-ranking-waterfall.md`: Architecture entry for Treemap, Account ranking, waterfall and after-tax toggle (#89, spec 6.1): main functions, UI markers and decisions.
- `ui-visibility.md`: Architecture entry for Wygląd i widoczność (#155): main functions, UI markers and decisions.
- `unpriced-instruments.md`: Architecture entry for Unpriced Instruments: main functions, UI markers and decisions.
- `valuation-snapshots.md`: Architecture entry for Valuation Snapshots (#115, ADR-0008): main functions, UI markers and decisions.
- `valuation.md`: Architecture entry for domain/valuation.py: main functions, UI markers and decisions.
- `version-installer.md`: Architecture entry for Version and installer (#99): main functions, UI markers and decisions.
- `view-scope-periods.md`: Architecture entry for View Scope and period selector (#71, spec 5 and 6.1): main functions, UI markers and decisions.
- `wyniki.md`: Architecture entry for Wyniki (#74, spec 6.1): main functions, UI markers and decisions.
- `xtb-import-reconciliation.md`: Architecture entry for XTB import and Reconciliation (L-17, spec 7): main functions, UI markers and decisions.
- `yahoo.md`: Architecture entry for sources/yahoo.py: main functions, UI markers and decisions.

## packaging/

- `kapita.iss`: Inno Setup recipe for the KAPITA Windows installer: per-user install, Start menu and desktop shortcuts, upgrades by fixed AppId
- `kapita.spec`: PyInstaller recipe freezing main.py into the windowed KAPITA folder build, with NiceGUI, migrations and icons as data

## prototypes/

- `dashboard_redesign_prototype.py`: Throwaway NiceGUI prototype comparing three Dashboard layouts and a golden theme on made-up demo data; not for production

## scripts/

- `build_installer.ps1`: Builds the KAPITA installer: runs PyInstaller on the spec, then Inno Setup with the version from the package
- `create_desktop_shortcut.ps1`: PowerShell script creating a Windows desktop shortcut that starts the console-less app window.
- `make_icons.py`: Cuts the KAPITA app icons (png and ico) out of the logo in packaging/; run only when the logo changes
- `new_migration.py`: Generates the next numbered migration by autogenerating against a scratch database, then ruff fixes and formats it.
- `screenshot.py`: Screenshots KAPITA's tabs with headless Chrome or Edge, running main.py --demo on a free port and stopping it after

## src/financial_app/

- `__init__.py`: Package marker for financial_app; holds the one version number, __version__ = 1.0.0
- `__main__.py`: Module entry point so the package can be run with python -m financial_app, starting the app.
- `app.py`: Application start-up: backs up and migrates the database, opens the native window or, with --browser or --demo, serves the UI in a browser; --demo seeds a made-up database in TEMP.

## src/financial_app/domain/

- `__init__.py`: Docstring marking the domain package as pure-Python calculations with no UI or database imports.
- `account_ranking.py`: Account ranking and treemap figures for the Total Dashboard: XIRR, TWR, P&L, Net Deposits and costs per Account, sorted with best and worst marked
- `account_value.py`: Shared definition of an Account's value and result today: cash, Positions, unrealised and FX results for the Portfolio and Dashboard
- `accounts.py`: Account Types, Tax Regime descriptions, Account field validation, and the refusal naming what still holds an Account from deletion
- `benchmarks.py`: Benchmarks: CPI, Instrument or Account with a pp/year offset, daily growth factors and the Portfolio-vs-benchmark comparison over a period.
- `bond_calendar.py`: Calendar of coupons, anniversaries and maturities of held Bond Series over the next 12 months, by View Scope
- `bond_drafts.py`: Drafts for matured Bond Series Lots (redemption, Rollover) and coupons of COI, ROR and DOR Lots, with the Sell or interest Transaction each confirms
- `bond_holdings.py`: Obligacje tab data: each Bond Series held in the View Scope with its Lots, gross and net values, rates and dates
- `bond_redemption.py`: Net value of a retail treasury bond on redemption: gross value less early-redemption fee and withheld Belka tax
- `bond_valuation.py`: Values Bond Series by MF letters and CPI or NBP estimates, including COI, ROR and DOR coupon accrual and the coupons they pay
- `bonds.py`: Polish retail treasury bond types, their terms, GUS CPI readings and NBP reference rates as pure-Python values
- `catalyst.py`: Price per Catalyst bond from its percent of nominal plus accrued interest, and the indexed nominal of IZ bonds
- `charts.py`: Dashboard chart data from History and Transactions: value, profit, XIRR, class shares and dividends by year, per scope and period
- `contribution_limits.py`: Contribution Limits rules: which transactions count towards each IKE, IKZE or OIPE yearly limit, bars and over-limit warnings
- `currencies.py`: Currency code check and the NBP Rate value type, plus the error raised when a rate is missing.
- `dashboard.py`: Dashboard totals, Account table, currency exposure and allocation from Transactions, prices, NBP Rates and History, plus estimated tax and profit by source
- `export.py`: Builds the transaction export rows with columns, amounts, origin and comment, independent of file format.
- `faq.py`: Parses the Pomoc FAQ Markdown into sections and questions; searches them ignoring case and Polish letters
- `formatting.py`: Polish number, amount and date formatting and parsing of typed input; the single formatter every screen uses.
- `history.py`: Tracks which days of Quote and NBP Rate history are cached, and computes the missing days to fetch.
- `inflation.py`: Inflation over a period from GUS monthly CPI, spread across days as the sheet's Benchmarki do, and the real return
- `instrument_search.py`: Instrument search result types, the swappable search protocol, and filling empty form fields from a chosen result.
- `instruments.py`: Instrument and Asset Class models, their validation, default Asset Classes, ISIN, metal, distribution policy and Multi-asset Split rules.
- `investment_goal.py`: Investment Goal for a View Scope: amount or FIRE target, progress, default monthly deposit and real forecast in today's PLN
- `lots.py`: The single FIFO engine that opens and consumes Lots for Positions and foreign cash, raising uncovered-sale errors.
- `metrics.py`: Pure History metrics: XIRR, TWR, drawdowns, max drawdown, volatility and daily change per Total or Account
- `multi_asset.py`: Multi-asset Instruments held in the View Scope, with their PLN value and split value per Asset Class, largest first
- `passive_income.py`: Passive income: Dividends and interest received, coupons forecast, monthly sums, 12-month average and the Monthly Income Goal.
- `periods.py`: Period presets and custom ranges for charts and results, with date calculation and text persistence
- `portfolio_history.py`: Computes daily Portfolio value and Net Deposits per Account and Asset Class from transactions and cached prices
- `prices.py`: Quote model, Price Source keys and names, and the per-Asset-Class Fallback Order deciding which sources to try.
- `profit_sources.py`: Splits the View Scope's result into price, FX, Dividends, interest, costs and taxes for the Dashboard waterfall
- `reconciliation.py`: Pairs broker Transactions with entered ones and classifies matches, broker-only and entered-only; resolves choices
- `recurring.py`: Recurring Rules: validated rule fields, occurrence schedule, and Drafts left after matching Transactions and skips
- `results.py`: Wyniki tab figures: period XIRR, TWR, drawdown, volatility and fixed-period returns per Total and Account, from History
- `sale_summary.py`: Sell Summary: Sale Pairs from the FIFO replay with attributed Dividends, and closed-position statistics (win rate, days, best, worst).
- `save_warnings.py`: Warnings a save of Transactions shows (cash shortfalls, over-limit contributions, unsplit Multi-asset), computed before and after the save; never blocks it
- `spreadsheet_import.py`: Pure conversion of the user's Inwestomat Transakcje sheet rows into Transaction drafts, with fingerprints for re-import skipping.
- `strategy.py`: Investment Strategy rules: Allocation Targets with tolerance bands, Instrument Targets, and the water-filling split of the Planned Deposit
- `term_deposits.py`: Term Deposit rules: contract fields, capitalisation periods, Belka-net interest, Accrued Interest, Drafts and capital locked by running deposits
- `transaction_filters.py`: Excel-like column filters and sort order for the Transakcje list; returns the filtered, sorted view of Transactions
- `transaction_form.py`: Transaction dialog rules without widgets: fields per Transaction Type and the Transaction they describe, or the field error
- `transactions.py`: Transaction types, drafts and builders for every kind, plus cash balances and cost and dividend totals per Account.
- `ui_visibility.py`: Hideable Dashboard elements and tabs, View Profiles (Podstawowy, Pełny, Własny), and the hidden set saved as JSON text
- `valuation.py`: Decides each Instrument's price and status from Manual Price or Quote, including metal spot conversion and badges.
- `valuation_snapshots.py`: Valuation Snapshot figures per View Scope and the change since one, split into market change and Net Deposits in between
- `view_scope.py`: View Scope logic: Total or one Account, its remembered setting, switcher entries and transaction filtering
- `xtb_import.py`: Reads XTB xStation statements into entries and broker Transaction drafts; pure, no file or UI access

## src/financial_app/persistence/

- `__init__.py`: Package marker for the SQLite and SQLAlchemy persistence layer.
- `accounts.py`: Saves, reads and deletes Accounts, enforcing case-insensitive unique names and refusing to delete a held Account
- `backup.py`: Copies the database to the backups folder at each start and keeps only the newest copies.
- `benchmarks.py`: Saves Benchmarks (add, show, delete) and seeds the sheet's default benchmarks and their Instruments once.
- `bond_data.py`: SQLite copy of the bond data sources (MF Bond Series, GUS CPI, NBP reference rates) and each source's fetch status
- `bond_drafts.py`: Lists pending bond Drafts (maturities and unentered coupons) and saves them as Transactions, all or nothing
- `bond_series.py`: Bond Series persistence: lists Series with their MF terms and rate corrections, saves corrections, finds or creates Series Instruments
- `contribution_limits.py`: Reads and saves yearly Contribution Limits per Account Type in SQLite
- `db.py`: Opens the SQLite engine and applies pending Alembic migrations at start-up.
- `deposit_drafts.py`: Computes pending Term Deposit interest and maturity Drafts from saved deposits and Transactions; confirms interest as Transactions
- `history.py`: Reads and writes cached Stooq Quote history and NBP Rate history, with the cover of fetched days.
- `instruments.py`: Saves and reads Asset Classes and Instruments, and deletes Instrument data including its Quotes and failures.
- `investment_goals.py`: Loads, saves and deletes the Investment Goal of each View Scope in the database
- `models.py`: SQLAlchemy ORM models describing the database tables; schema changes go through migrations
- `nbp_rates.py`: SQLite cache of NBP Rates keyed by currency and day
- `paths.py`: Resolves the user's data, backup and log folders outside the repository; moves the legacy FinancialApp data folder to KAPITA.
- `quotes.py`: Saves and reads daily Instrument Quotes and the last price refresh status
- `reconciliation.py`: Saves a broker Reconciliation's choices all or none and reads handled, unreconciled and incoming transfers
- `recurring_rules.py`: Saves Recurring Rules and their skips, computes their Drafts and confirms them as Transactions
- `reset.py`: Clears all portfolio data after a backup and restores default Asset Classes
- `settings.py`: Reads and writes text application settings by key in the app_settings table
- `strategies.py`: Reads and saves Investment Strategies for Total and each Account, with their Allocation and Instrument Targets
- `term_deposits.py`: Saves, edits, ends, renews and deletes Term Deposits on Deposit Accounts, and lists them
- `transactions.py`: Saves, edits, deletes and lists Transactions, replaying positions to block invalid changes
- `valuation_snapshots.py`: Saves Valuation Snapshots per View Scope and day, and reads the newest snapshot from an earlier day

## src/financial_app/persistence/migrations/

- `env.py`: Alembic environment wiring the app connection and model metadata into migration runs.
- `script.py.mako`: Template Alembic uses to generate new migration revision files.

## src/financial_app/persistence/migrations/versions/

- `0001_initial_schema.py`: Initial migration creating the app_settings key-value table.
- `0002_accounts.py`: Migration creating the accounts and account cash currencies tables.
- `0003_transactions.py`: Migration creating the transactions table for PLN deposits and withdrawals.
- `0004_asset_classes_and_instruments.py`: Migration creating asset classes seeded with the sheet's twelve, and the instruments table.
- `0005_trades.py`: Migration adding instrument, quantity, price and commission columns to transactions for Buys and Sells.
- `0006_nbp_rates.py`: Migration adding the NBP Rates cache table and NBP and FX rate columns on transactions.
- `0007_foreign_cash.py`: Migration adding cash currency and Currency Exchange direction columns to transactions.
- `0008_fx_conversion_fee.py`: Migration adding the broker FX Conversion Fee percent column to transactions.
- `0009_dividends.py`: Migration adding gross amount and withholding tax columns for Dividends and DRIPs
- `0010_splits_and_transfers.py`: Migration adding Split ratio and target Account for Cash and Security Transfers
- `0011_transaction_origin.py`: Migration adding Transaction origin and import row fingerprint for spreadsheet imports
- `0012_source_symbols_and_quotes.py`: Migration adding per-source Instrument symbols and the daily Quotes table
- `0013_price_failures.py`: Migration adding storage for the last price refresh failures per Instrument
- `0014_price_history.py`: Migration adding local cache tables for Stooq price history and NBP Rate history
- `0015_physical_metals.py`: Migration adding metal weight per unit and buyback spread for physical metals
- `0016_instrument_isin.py`: Migration adding the optional ISIN column to Instruments
- `0017_fund_details.py`: Migration adding fund TER, Distribution Policy and domicile columns
- `0018_fallback_orders.py`: Migration giving each Asset Class its own Fallback Order column, filled with the spec 4.1 defaults.
- `0019_multi_asset_splits.py`: Migration 0019 creates the multi_asset_shares table holding each Instrument's Multi-asset Split
- `0020_multi_asset_class.py`: Alembic revision adding the asset_classes multi_asset flag and marking the seeded Multi-asset class
- `0021_investment_strategies.py`: Migration creating the strategy, class target and instrument target tables for Investment Strategies
- `0022_bond_data.py`: Alembic migration adding the bond data tables: Bond Series, CPI, reference rates and fetch status
- `0023_bond_rate_corrections.py`: Migration adding the bond rate corrections table and clearing imported Manual Prices on Bond Series
- `0024_redeemed_lots.py`: Migration 0024 adds the nullable lot_id column to transactions, naming the Lot an Early Redemption Sell redeems
- `0025_catalyst_bond_prices.py`: Migration 0025: moves treasury bonds to Bossa per-bond prices and drops the old percent-of-nominal Bossa Quotes
- `0026_reconciliation.py`: Migration adding broker ids, reconciled dates and the skipped broker rows table for reconciliation
- `0027_benchmarks.py`: Migration 0027 creates the benchmarks table (kind, Instrument or Account, offset, shown, position).
- `0028_polish_benchmark_etfs.py`: Migration 0028 drops the WSE:WIG and WSE:SWIG80TR default benchmarks left on Stooq so the Beta ETF defaults come in.
- `0029_contribution_limits.py`: Migration creating the contribution_limits table and seeding 2026 limits
- `0030_quantity_decimals.py`: Migration adding Instrument quantity_decimals, filled from existing Transaction quantities and set to 8 for crypto
- `0031_valuation_snapshots.py`: Migration creating the valuation_snapshots table
- `0032_investment_goals.py`: Migration creating the investment_goals table
- `0033_recurring_rules.py`: Migration 0033: creates recurring rule and skip tables and the Transaction columns linking to a rule
- `0034_commission_currency.py`: Migration adding the transactions commission_currency column, defaulting to PLN, for commissions paid in foreign cash.
- `0035_recurring_rule_target.py`: Migration adding the nullable target_account_id column to recurring_rules for Cash Transfer Recurring Rules.
- `0036_term_deposits.py`: Alembic migration 0036 creating the term_deposits table and linking interest Transactions to deposit periods

## src/financial_app/sources/

- `__init__.py`: Package marker describing the external price sources package
- `analizy.py`: Fund and PPK Quotes, valuation history for History, and fund search through the undocumented analizy.pl API
- `bankier.py`: Fetches fund and PPK Quotes from bankier.pl pages as the fallback price source
- `benchmarks.py`: Builds each saved benchmark's growth from the CPI, price and NBP caches and compares it with History.
- `bond_data.py`: Fetches and parses the MF bond file, GUS CPI and NBP reference rates, refreshing their SQLite copies at most once a day
- `bossa.py`: Fetches GPW, NewConnect, ETF and bond Quotes in PLN from the Bossa JSON API
- `catalyst.py`: Fetches Catalyst bonds' nominal and accrued interest from gpwcatalyst.pl and IZ indexation coefficients from gov.pl
- `current_prices.py`: Today's valuation inputs shared by the Portfolio and the Dashboard: Instrument prices and NBP Rates from the last business day before today, each currency fetched once
- `dashboard.py`: Computes today's Dashboard of a View Scope from the database, shared by the Dashboard and the Investment Strategy
- `demo_data.py`: Seeds the made-up demo Portfolio (two Accounts, DEMO Instruments, a year of Transactions) for the --demo start
- `export.py`: Writes the Transactions list to CSV and XLSX files for export
- `history.py`: Returns an Instrument's Quotes in a date range, fetching missing days from Yahoo, analizy.pl or Stooq into cache
- `nbp.py`: Gets NBP exchange rates from the NBP API through the local cache
- `passive_income.py`: Loads the passive-income items: income received from Transactions and the coupons and Term Deposit interest not entered for the next 12 months.
- `portfolio_history.py`: Fetches History prices and NBP Rates into cache and computes daily values, cached until invalidated
- `prices.py`: Refreshes held Instruments' Quotes from price sources in fallback order and records failures
- `spreadsheet.py`: Previews and imports Transactions and Instruments from the user's Inwestomat spreadsheet
- `stooq.py`: Stooq history source for GPW stocks and indices; fetches daily closes via CSV with API key and browser proof-of-work check
- `todays_view.py`: Loads today's portfolio state once (Transactions, Accounts, Positions, prices, NBP Rates) for the tabs and Dashboard to share
- `transaction_saving.py`: Single save path for Transactions (dialog, sheet import, XTB Reconciliation, bond Drafts) that returns the save's warnings
- `valuation_snapshots.py`: Takes a Valuation Snapshot after a Successful Refresh and computes the Dashboard's change since the last one
- `xtb.py`: Reads, previews and applies XTB statement imports, matching accounts and tickers and remembering matches
- `yahoo.py`: Yahoo Finance source for current quotes and Instrument search; converts GBp pence and parses chart and search responses

## src/financial_app/ui/

- `__init__.py`: Package marker for the NiceGUI user interface layer, a thin layer over domain and persistence
- `account_ranking.py`: Total Dashboard's Accounts treemap and sortable Account ranking; clicking a tile switches the View Scope to that Account
- `accounts.py`: Ustawienia Konta card: lists Accounts, opens the add and edit dialog, and deletes an unused Account
- `benchmarks.py`: Benchmarki tab: comparison table with chart toggles and delete, the add form, and value charts over the period.
- `bond_data.py`: Header status listing failing bond data sources with their reasons, shown only while one keeps failing
- `bond_drafts.py`: Dochód stały tab's "Do zatwierdzenia" list of bond maturities, unpaid coupons, and Term Deposit interest and maturities, with its header count.
- `bond_series.py`: Bond Series rate summary and dialog for correcting MF rates by hand in Ustawienia Instrumenty
- `bonds.py`: Dochód stały tab UI: Term Deposits section, expandable Bond Series table with Lots and values, the "Do zatwierdzenia" list, and the 12-month calendar.
- `changes.py`: Window change events: the Change enum, the TODAYS_VALUE set, and ChangeEvents, which redraws each tab or header element that declared the published changes.
- `charts.py`: Dashboard's nine ECharts charts, the profit waterfall, and shared PLN line and bar chart helpers for other tabs.
- `contribution_limits.py`: Contribution Limits UI: yearly limits in Ustawienia and this year's Dashboard bars
- `dashboard.py`: Dashboard tab UI: totals, price status, Account table, exposure, charts, Account treemap and ranking, Investment Goal tile, and the after-tax toggle
- `deposit_drafts.py`: Dochód stały rows for Term Deposit interest and maturity Drafts: confirm, edit amounts, end or renew a matured deposit
- `dialogs.py`: Draggable dialog support with no backdrop, so the screen behind stays readable
- `faq.md`: Polish FAQ text shown on the Pomoc tab; sections, questions with slugs, and links to tabs
- `fund_details.py`: Builds the short fund detail texts (TER, Distribution Policy, domicile) shared by Instrument list and Portfolio
- `help.py`: Pomoc tab; shows the FAQ as collapsible questions with a search and Przejdź do buttons to tabs
- `history.py`: Shared per-database History window state: background fetch, progress and failure status, cached days
- `import_sheet.py`: Ustawienia import section that previews the Transakcje spreadsheet and saves it only after user decisions
- `info.py`: Hover "i" icon and card title helper that show explanatory text in Dashboard and Wyniki cards
- `instruments.py`: Ustawienia Klasy aktywów and Instrumenty cards: editable Asset Classes and the Instrument catalog with its dialog
- `investment_goal.py`: Dashboard Investment Goal tile with progress and real forecast, and a dialog to set the goal as amount or FIRE
- `multi_asset.py`: Multi-asset tab and split editor: edits an Instrument's Multi-asset Split and lists held Multi-asset Instruments by Asset Class
- `passive_income.py`: Dochód pasywny tab: year navigation, Monthly Income Goal, tiles, monthly chart and table with progress, forecast coupons.
- `periods.py`: Period selector UI: preset buttons and custom range inputs, remembered per user and redrawing listeners
- `portfolio.py`: Read-only Portfolio tab: per-Account cards with cash balances, valued Positions, Lots, FX result and dividends
- `price_sources.py`: Ustawienia Źródła wycen card where the user stores the personal Stooq API key
- `recurring_drafts.py`: Due Recurring Rule Drafts in the Transakcje tab and the header count; confirm, edit or skip each
- `recurring_rules.py`: Ustawienia section listing Recurring Rules, with the rule dialog and its skipped occurrences
- `reset.py`: Ustawienia Wyczyść dane card that clears the whole portfolio after a warning and typed confirmation
- `results.py`: Wyniki tab page: result tiles, drawdown chart and per-Account results table under the period selector
- `sale_summary.py`: Podsumowanie sprzedaży tab: Sale Pairs of the scope and period with the closed-position statistics tiles.
- `save_warnings.py`: Shows save warnings as notifications, the same way wherever Transactions were saved
- `settings.py`: Builds the Ustawienia page by assembling its sections: Accounts, Asset Classes, Instruments, sources, import, reset
- `shell.py`: Main app window shell: left menu, header with refresh status and View Scope, and the transaction button
- `strategy.py`: Strategie inwestycyjne tab, Dashboard strategy section and post-refresh notice for classes outside their tolerance band
- `term_deposits.py`: Lokaty section of Dochód stały: running Term Deposits with accrued interest, and the dialog to add, edit, break or delete one
- `transaction_dialog.py`: Transaction dialog for adding, editing and deleting every supported transaction type, bound to the form model
- `transactions.py`: Transakcje tab: the Transaction list with column sorting and filters
- `unpriced.py`: Ustawienia Instrumenty bez wyceny card listing held Instruments lacking an automatic price, with reasons
- `view_scope.py`: View Scope header switcher and breadcrumbs, listing Accounts by value with share and daily change
- `visibility.py`: Window Layout of hidden elements, plus the Ustawienia switches and View Profile presets that change it
- `xtb_import.py`: Ustawienia card for importing XTB statements and resolving the Reconciliation before applying

## tests/

- `conftest.py`: Shared test setup: sets the testmon coverage core, marks user_simulation tests as ui, and gives should_see and should_not_see 5 s to match.
- `test_account_deletion.py`: Tests deleting an Account that nothing names and the refusals naming what still holds an Account
- `test_account_ranking_domain.py`: Tests Account ranking figures, sorting, best and worst marks and treemap tiles
- `test_account_ranking_ui.py`: Tests the Dashboard's Account treemap and ranking, profit waterfall and after-tax toggle
- `test_account_value_domain.py`: Tests the domain definition of an Account's value and result today
- `test_accounts_domain.py`: Tests Account Types, Tax Regime registry and AccountDraft validation rules
- `test_accounts_repository.py`: Tests saving, listing and editing Accounts in SQLite, including unique names
- `test_accounts_ui.py`: UI tests for Ustawienia Konta: adding, editing and deactivating Accounts without a browser
- `test_accounts_without_pln_domain.py`: Tests domain rules for commissions paid from foreign cash on an Account without PLN: FIFO cash, valuation, balances.
- `test_accounts_without_pln_form.py`: Tests the transaction dialog rules on an Account without PLN: offered transaction kinds and commission currency.
- `test_accounts_without_pln_repository.py`: Tests saving and listing a trade whose commission is paid in foreign cash on an Account without PLN.
- `test_accounts_without_pln_ui.py`: End-to-end UI test of a Buy on an Account without PLN, paying the commission from its foreign cash.
- `test_analizy_history.py`: Tests fund and PPK valuation history from analizy.pl on saved responses, and the source order for History
- `test_analizy_search.py`: Tests for analizy.pl fund and PPK search on saved, trimmed responses without network
- `test_analizy_source.py`: Tests the analizy.pl fund and PPK quote source against saved API responses
- `test_architecture.py`: Architecture test enforcing that the domain core does not import UI or database code
- `test_backup.py`: Tests database backup copies and the retention of the newest backups
- `test_bankier_source.py`: Tests the bankier.pl fund and PPK quote source against saved pages
- `test_benchmarks_domain.py`: Tests benchmark growth, cash before data, offsets, CPI spreading, Account benchmarks and offset parsing.
- `test_benchmarks_repository.py`: Tests saving benchmarks, seeding defaults once, dropping them with Instruments or Accounts, and cache-based comparison.
- `test_benchmarks_ui.py`: UI tests of the Benchmarki tab: defaults, CPI, adding, hiding, removing and the Account scope.
- `test_bond_calendar_domain.py`: Tests for the bond calendar domain: event kinds, amounts, View Scope filtering and day ordering
- `test_bond_data.py`: Tests for bond data parsers, SQLite persistence and daily refresh rules on saved fixtures
- `test_bond_data_ui.py`: UI tests for the bond data header status and its error dialog
- `test_bond_drafts_domain.py`: Tests Draft rules for maturities, Rollovers and coupons: which Lots are Drafts and what they redeem, roll or pay
- `test_bond_drafts_repository.py`: Tests saving bond Drafts (redemptions, Rollovers and coupon interest) as Transactions, including rollback on failure
- `test_bond_drafts_ui.py`: Tests the Drafts list in the Obligacje tab (maturities and coupons) and the header count
- `test_bond_holdings_domain.py`: Tests the Obligacje tab's Series holdings: Lot sums, rate labels, Tax Regime effect and scope filtering
- `test_bond_parity.py`: Parity test of bond valuation against the user's spreadsheet Obligacje tab, skipped without reference data
- `test_bond_purchase_ui.py`: UI tests for buying retail treasury bonds in the transaction dialog's bond mode
- `test_bond_rates_ui.py`: UI tests for correcting a Bond Series' MF rates in Ustawienia Instrumenty
- `test_bond_redemption_domain.py`: Tests bond early-redemption fees, Belka withholding, anniversaries and maturity dates
- `test_bond_series_choice.py`: Tests the MF Series a past bond purchase may pick, their newest-first order and sale windows
- `test_bond_series_domain.py`: Domain tests for Bond Series naming and corrected MF rates
- `test_bond_series_repository.py`: Repository tests for Bond Series as Instruments with saved rate corrections
- `test_bond_valuation.py`: Unit tests for bond valuation: MF, CPI and NBP rates, linear accrual, grosz rounding and coupon payouts
- `test_bond_valuation_ui.py`: UI tests for Bond Series values in the Portfolio, with per-Lot rates and labels from MF or CPI
- `test_bonds_ui.py`: UI tests for the Obligacje tab and the Dashboard's after-tax bond deduction
- `test_bossa_source.py`: Tests the Bossa JSON API quote source against saved responses
- `test_catalyst_domain.py`: Tests Catalyst bond price per bond and the IZ indexed nominal
- `test_catalyst_source.py`: Tests Catalyst nominal and accrued interest parsing and IZ indexation on saved pages
- `test_changes.py`: Tests for the change events: each change reaches its declared subscribers once, in subscription order, including changes published during a publish.
- `test_chart_zoom_ui.py`: UI tests that a chart card's zoom button opens the same chart in a near-window-sized dialog.
- `test_charts_domain.py`: Unit tests for the Dashboard chart data: value, profit, XIRR, class shares and dividends by year
- `test_clear_data_repository.py`: Tests that clearing the portfolio removes user data and restores default Asset Classes
- `test_clear_data_ui.py`: UI tests for the Wyczyść dane confirmation flow in Ustawienia
- `test_contribution_limits_domain.py`: Tests which transactions count towards Contribution Limits, the bars and the over-limit warning
- `test_contribution_limits_repository.py`: Tests saving, seeding and removing yearly Contribution Limits in the database
- `test_contribution_limits_ui.py`: UI tests for Contribution Limits on the Dashboard, in Ustawienia and the warning after a save
- `test_conversion_fee_domain.py`: Domain tests for the broker FX Conversion Fee on foreign-currency Buys and Sells
- `test_conversion_fee_ui.py`: UI tests for the FX Conversion Fee and payment source in the transaction dialog
- `test_dashboard_charts_ui.py`: UI tests that the Dashboard's nine charts follow the View Scope and the period
- `test_dashboard_domain.py`: Tests the Dashboard domain totals, Account table and currency exposure
- `test_dashboard_ui.py`: UI tests for the Dashboard tab: totals, Account table, currency exposure and price status
- `test_database.py`: Checks that the ORM models and Alembic migrations stay in sync
- `test_demo_data.py`: Tests the made-up demo Portfolio, the demo database in TEMP and the start options
- `test_dividends_domain.py`: Domain tests for Dividends, interest, Costs and DRIP calculations
- `test_dividends_repository.py`: Tests saving Dividends, Costs and DRIPs to SQLite
- `test_dividends_ui.py`: UI tests for Dividends, Costs and DRIP in the transaction dialog, Transakcje and Portfolio
- `test_early_redemption_domain.py`: Tests Early Redemption domain rules: a Sell naming its Lot, the early-redemption fee and the tax withheld
- `test_early_redemption_repository.py`: Tests saving an Early Redemption, its named Lot kept across reloads, and guarding that Lot's Buy
- `test_early_redemption_ui.py`: Tests the early redemption in the "+" dialog: choosing the Lot and the prefilled fee and tax
- `test_export_domain.py`: Tests the export rows built for the Transakcje list across all Transaction types
- `test_export_files.py`: Tests the CSV and XLSX export files, including Polish characters and read-back
- `test_export_ui.py`: UI tests for the Transakcje export buttons saving CSV and XLSX files
- `test_fallback_order_ui.py`: UI tests for editing an Asset Class's Fallback Order in Ustawienia: showing, removing, adding, moving and saving sources.
- `test_faq_domain.py`: Unit tests of FAQ Markdown parsing, format errors and search
- `test_foreign_cash_domain.py`: Domain tests for foreign cash Lots, Currency Exchange and FX result per Account
- `test_foreign_cash_repository.py`: Tests saving Currency Exchanges and foreign-cash Buys to SQLite
- `test_foreign_cash_transfer_domain.py`: Tests foreign-currency Cash Transfers in the domain: oldest cash Lots move with dates and costs, no FX result, NBP-rate PLN value.
- `test_foreign_cash_transfer_form.py`: Tests the transaction dialog rules for foreign-currency Cash Transfers: source currencies offered, only targets holding the currency.
- `test_foreign_cash_transfer_repository.py`: Tests saving foreign-currency Cash Transfers: both Accounts must hold the currency.
- `test_foreign_cash_transfer_ui.py`: End-to-end UI test of a USD Cash Transfer without the network.
- `test_foreign_cash_ui.py`: End-to-end UI tests for foreign cash, Currency Exchange and FX result
- `test_foreign_trades_ui.py`: End-to-end UI tests for foreign-currency Buys and Sells using the NBP Rate
- `test_formatting.py`: Tests the Polish number, date and count formatting and typed-input parsing helpers
- `test_fund_details_ui.py`: UI tests for a fund's TER, Distribution Policy and domicile in the dialog and Portfolio
- `test_fx_effect_domain.py`: Tests the FX part of foreign Positions' results from the PLN and foreign costs of FIFO Lots
- `test_glossary.py`: Test that GLOSSARY.md lists exactly the terms defined in CONTEXT.md
- `test_help_ui.py`: UI tests of the Pomoc tab search and navigation buttons, and the Dashboard first-steps banner
- `test_history_domain.py`: Tests which days of a price history still need fetching given cached days
- `test_history_parity.py`: Parity test of History against the user's spreadsheet Historia tab at each month end, skipped without reference data
- `test_import_sheet_ui.py`: UI tests for the Ustawienia spreadsheet import: preview first, then save, on a synthetic workbook
- `test_inflation.py`: Tests inflation over periods from GUS monthly CPI readings and the real return it gives
- `test_instrument_search_domain.py`: Tests that a chosen Instrument search result fills only the empty Instrument form fields.
- `test_instrument_search_ui.py`: Tests searching an Instrument by ISIN, name or symbol in the Instrument dialog on saved Yahoo responses.
- `test_instruments_domain.py`: Tests Instrument and Asset Class validation rules, including fund and distribution policy fields.
- `test_instruments_repository.py`: Tests saving Asset Classes and Instruments in SQLite, including uniqueness and updates.
- `test_instruments_ui.py`: Tests the Klasy aktywów and Instrumenty sections of Ustawienia, run without a browser.
- `test_investment_goal_domain.py`: Tests Investment Goal values, progress, default monthly deposit and real forecast
- `test_investment_goal_repository.py`: Tests saving Investment Goals: one per View Scope, replaced, removed and gone with their Account
- `test_investment_goal_ui.py`: Tests setting, editing and removing an Investment Goal on the Dashboard per View Scope
- `test_lots_domain.py`: Tests the FIFO Lot engine and the Positions it produces from Transactions.
- `test_metrics_domain.py`: Unit tests for History metrics: XIRR, TWR, drawdown and volatility per Total or Account
- `test_multi_asset_domain.py`: Tests Multi-asset Split rules in the domain: validation, class parts, History, Dashboard allocation and holdings
- `test_multi_asset_repository.py`: Tests saving Multi-asset Splits with their Instruments, Asset Class rules, and their removal on reset
- `test_multi_asset_ui.py`: UI tests for the Multi-asset split in the Instrument dialog, the split dialog after a buy, and the Multi-asset tab
- `test_nbp_rates.py`: Tests fetching and caching NBP D-1 rates from saved API responses, without the network.
- `test_passive_income_domain.py`: Tests received income kinds, monthly sums by scope, goal progress, the 12-month average and goal parsing.
- `test_passive_income_ui.py`: UI tests of the Dochód pasywny tab: received and forecast by month, the goal, years and the scope.
- `test_paths.py`: Tests the default data directory (outside the repository, named KAPITA), the override, and the legacy folder move without overwriting new data.
- `test_periods_domain.py`: Unit tests for period presets, custom ranges and period text persistence
- `test_physical_metals_ui.py`: Tests physical metal Instruments with weight per unit and Buyback Spread in the dialog and Portfolio.
- `test_portfolio_history_domain.py`: Unit tests for the History engine: daily value per Account and Asset Class and Net Deposits
- `test_portfolio_history_service.py`: Tests the Portfolio history service: fetching prices into the cache, then computing history from it, on saved responses.
- `test_portfolio_parity.py`: Tests that the app's Portfolio matches the user's spreadsheet Portfolio tab within 0.01 PLN, skipped without the workbook.
- `test_price_history.py`: Tests an Instrument's Quotes in a date range, fetching missing days from Stooq once and caching them.
- `test_price_history_ui.py`: Tests the Stooq Source Symbol in the Instrument dialog and the Stooq API key in Ustawienia.
- `test_price_refresh.py`: Tests refreshing held Instruments' Quotes from Price Sources in order, using fake sources.
- `test_prices_domain.py`: Tests the order of Price Sources per Instrument and when start-up price refresh is due.
- `test_prices_repository.py`: Tests saving Source Symbols and Quotes in SQLite.
- `test_prices_ui.py`: Tests Source Symbols in the Instrument dialog, Portfolio valuation from Quotes and refresh status badges.
- `test_profit_sources_domain.py`: Tests the profit-by-source split adds up to the result the Dashboard tiles show
- `test_reconciliation_domain.py`: Tests pairing of broker and entered Transactions in the Reconciliation domain logic
- `test_recurring_domain.py`: Tests Recurring Rule schedules, Draft matching with Transactions, and rule validation messages
- `test_recurring_repository.py`: Tests saving Recurring Rules and skips, confirming Drafts, and cascading deletes against the database
- `test_recurring_ui.py`: UI tests for Recurring Rules in Ustawienia and their Drafts in Transakcje and the header
- `test_results_domain.py`: Tests for the Wyniki tab's period results and fixed-period rows per Total and Account
- `test_results_ui.py`: UI tests for the Wyniki tab: tiles, drawdown chart, results table and pending state
- `test_sale_summary_domain.py`: Tests Sale Pairs across Lots, Splits and DRIPs, Dividend and coupon attribution, statistics and the view filter.
- `test_sale_summary_ui.py`: UI tests of the Podsumowanie sprzedaży tab: pairs, statistics, Account scope and an empty period.
- `test_save_warnings_domain.py`: Tests the save warnings computed from Transactions before and after a save
- `test_shell.py`: Smoke tests of the app shell's tabs and navigation, run without a browser.
- `test_splits_and_transfers_domain.py`: Tests Splits, Cash Transfers and Security Transfers in the FIFO engine and Cash Balances.
- `test_splits_and_transfers_repository.py`: Tests saving Splits, Cash Transfers and Security Transfers in SQLite.
- `test_splits_and_transfers_ui.py`: Tests Splits, Cash Transfers and Security Transfers in the transaction dialog and Transakcje list.
- `test_spreadsheet_import.py`: Tests importing the Transakcje sheet on a synthetic workbook with no real data.
- `test_startup.py`: Smoke test of the real entry point: builds the database and shows the window.
- `test_startup_refresh_ui.py`: Tests the background price refresh at start-up with fake sources and a fixed clock.
- `test_stooq_source.py`: Tests the Stooq price history source on saved CSV and browser-challenge responses, without the network.
- `test_strategies_repository.py`: Tests saving Investment Strategies for Total and per Account, and their removal on deletes and portfolio reset
- `test_strategy_domain.py`: Tests Investment Strategy rules: tolerance bands, Instrument Targets and the Planned Deposit split
- `test_strategy_ui.py`: UI tests for the Strategie inwestycyjne tab, the Dashboard strategy section and the out-of-band notice
- `test_symbol_check.py`: Unit tests for the Sprawdź symbol check: quote, currency mismatch warning, and error cases on fake sources
- `test_symbol_check_ui.py`: UI tests for the Sprawdź buttons in the Instrument dialog, on fake sources without network
- `test_symbol_fields_ui.py`: UI tests for the Instrument dialog's Source Symbol fields, ordered by the Asset Class's Fallback Order.
- `test_term_deposits_domain.py`: Tests of Term Deposit interest periods, accrued interest, Drafts and locked capital
- `test_term_deposits_repository.py`: Tests saving Term Deposits and confirming their Drafts against the database
- `test_term_deposits_ui.py`: UI tests of adding Term Deposits and handling their Drafts in the Dochód stały tab
- `test_term_deposits_valuation.py`: Tests Term Deposit interest counted in Account value, history, Dashboard profit and save warnings
- `test_todays_view.py`: Tests today's View state loaded once for the tabs, on an in-memory database with fixed NBP Rates
- `test_trades_ui.py`: Tests PLN Buys and Sells end to end through the transaction dialog, Transakcje list and Portfolio.
- `test_transaction_edit_ui.py`: UI tests for editing and deleting a Transaction from the Transakcje list, including blocked edits
- `test_transaction_filters_domain.py`: Domain tests for the Transakcje list's column filters, sort order and value options
- `test_transaction_filters_ui.py`: UI tests for Transakcje column headers: sorting, filter menus, clearing filters and the filtered export
- `test_transaction_form_domain.py`: Tests the transaction dialog's field rules and draft building without widgets
- `test_transaction_saving.py`: Tests saving Transactions on in-memory SQLite: the save, the Bond Series it creates and its warnings
- `test_transactions_domain.py`: Domain tests for Deposits, Withdrawals, trade amounts, validation and per-Account cash balances
- `test_transactions_repository.py`: Repository tests for saving, listing, editing and deleting Transactions in SQLite, with FIFO coverage checks
- `test_transactions_ui.py`: UI tests for Deposits and Withdrawals from the plus dialog, Transakcje list and Portfolio Cash Balance
- `test_ui_visibility_domain.py`: Tests of the hideable elements, View Profile presets and the hidden set's text round trip
- `test_ui_visibility_ui.py`: UI tests of hiding Dashboard tiles, charts and tabs, and of the Ustawienia View Profile presets
- `test_unpriced_domain.py`: Domain tests for the Instrumenty bez wyceny list: which held Instruments lack an automatic price and why
- `test_unpriced_ui.py`: UI tests for the Instrumenty bez wyceny section in Ustawienia, including opening and fixing a symbol
- `test_valuation_domain.py`: Domain tests for Instrument price selection, PLN conversion, staleness badges and metal spot valuation
- `test_valuation_snapshots_domain.py`: Tests the change since a Valuation Snapshot split into market change and Net Deposits
- `test_valuation_snapshots_repository.py`: Tests saving Valuation Snapshots: one per View Scope and day, and reading the newest earlier one
- `test_valuation_snapshots_ui.py`: Tests Valuation Snapshots in the window: snapshot after a Successful Refresh and the Dashboard change since one
- `test_view_scope_domain.py`: Tests the View Scope domain: Total or one Account, its text setting, and the Accounts the switcher offers.
- `test_view_scope_ui.py`: UI tests for the View Scope switcher, breadcrumbs, scope-following tabs and the period selector.
- `test_windowless.py`: Tests that windowless launches redirect stdout and stderr to a log file while console launches stay untouched
- `test_xtb_import_domain.py`: Tests reading XTB statements into entries and Transaction drafts
- `test_xtb_import_ui.py`: Tests the XTB import card in Ustawienia: matching, resolving and applying without a browser
- `test_xtb_parity.py`: Checks the user's XTB exports against XTB's own positions and cash; skipped without reference data
- `test_xtb_reconciliation.py`: Tests the XTB import and Reconciliation against a database with synthetic statements
- `test_yahoo_search.py`: Tests Yahoo Instrument search by ISIN and name on saved responses, with error handling
- `test_yahoo_source.py`: Tests Yahoo chart quotes on saved responses: currency, pence conversion, crypto rate and error messages
- `xtb_rows.py`: Builds synthetic XTB statement workbooks in xStation's layout for tests

## tests/fixtures/analizy/

- `FTI022_A_USD.json`: Saved analizy.pl fund quotation response for a USD Franklin Technology fund, used by tests
- `FTI068_AH_EUR.json`: Saved analizy.pl API response for a EUR fund, used to test the analizy price source offline
- `PZU01.json`: Saved analizy.pl quotation response for the PZU Akcji KRAKOWIAK fund, used by tests
- `PZU60.json`: Saved analizy.pl API response for the PZU60 PPK fund in PLN, for offline price source tests

## tests/fixtures/analizy/history/

- `PZU01.json`: Saved analizy.pl valuation history response of a fund, for offline history tests

## tests/fixtures/analizy/search/

- `LU0109392836.json`: Saved analizy.pl search response for an ISIN query returning one Franklin fund
- `PPK_2060_PZU.json`: Saved analizy.pl search response for a PPK query returning the PPK inPZU 2060 fund
- `PZU_Akcji_Krakowiak.json`: Saved analizy.pl search response for PZU Akcji Krakowiak, including a former-name listing
- `Quercus.json`: Saved analizy.pl search response for Quercus funds, used by search tests

## tests/fixtures/bankier/

- `fundusze_QRS32.html`: Trimmed bankier.pl fund page for QRS32, the fallback price source test input
- `ppk_PZU60.html`: Trimmed bankier.pl PPK page for PZU60, the fallback price source test input

## tests/fixtures/bossa/

- `_cat_bonds.json`: Trimmed Bossa API response listing Catalyst bond quotes, for offline Bossa source tests
- `_cat_etf.json`: Trimmed Bossa API response listing ETF and ETC quotes, for offline Bossa source tests
- `_cat_nConnect.json`: Trimmed Bossa API response listing NewConnect quotes, for offline Bossa source tests
- `_cat_shares.json`: Trimmed Bossa API response listing GPW shares and PDA quotes, for offline Bossa source tests

## tests/fixtures/catalyst/

- `instrumenty-notowane.html`: Trimmed gpwcatalyst.pl instrument listing page, for offline Catalyst source tests

## tests/fixtures/gus/

- `cpi.csv`: Saved GUS consumer price index CSV fixture for the bond data parser tests
- `page.html`: Saved stat.gov.pl page fixture linking to the GUS CPI CSV file

## tests/fixtures/indexation/

- `wspolczynniki-indeksacji.html`: Trimmed gov.pl MF indexation coefficients page, for offline Catalyst source tests

## tests/fixtures/mf/

- `dane_obligacji_detalicznych.xls`: Saved MF retail bond data .xls file fixture for the bond parser tests
- `page.html`: Saved gov.pl page fixture linking to the MF retail bond data file

## tests/fixtures/nbp/

- `usd_2025-12-24_2026-01-06.json`: Saved NBP API response with USD mid rates for late December 2025, for offline NBP tests
- `usd_2026-03-24_2026-04-06.json`: Saved NBP API response with USD mid rates for late March 2026, for offline NBP tests

## tests/fixtures/nbp_reference/

- `stopy_procentowe_archiwum.xml`: Saved NBP reference rate archive XML fixture for the reference rate parser tests

## tests/fixtures/stooq/

- `cdr.csv`: Illustrative Stooq daily OHLC CSV for CD Projekt, used by Stooq history tests
- `challenge.html`: Saved Stooq browser-check page with a SHA-256 proof-of-work script, used by challenge-answering tests
- `wig.csv`: Illustrative Stooq daily OHLC CSV for the WIG index, used by Stooq history tests

## tests/fixtures/yahoo/

- `0LX1.IL.json`: Saved Yahoo chart API response for CD Projekt on the London IOB listing, used by Yahoo source tests
- `7CD.DU.json`: Saved Yahoo chart API response for CD Projekt on Dusseldorf, used by Yahoo source tests
- `7CD.F.json`: Saved Yahoo chart API response for CD Projekt on Frankfurt, used by Yahoo source tests
- `7CD.MU.json`: Saved Yahoo chart API response for CD Projekt on Munich, used by Yahoo source tests
- `AAPL.json`: Saved Yahoo chart API response for Apple stock in USD, used by Yahoo source tests
- `BP.L.json`: Saved Yahoo chart API response for BP in GBp on London, used by Yahoo source tests
- `BTC-USD.json`: Saved Yahoo chart API response for Bitcoin in USD, used by Yahoo source tests
- `CDR.WA.json`: Saved Yahoo chart API response for CD Projekt on the Warsaw exchange in PLN, used by Yahoo source tests
- `ISAC.L.json`: Saved Yahoo chart API response for an iShares ACWI ETF on London, used by Yahoo source tests
- `ISAC.MI.json`: Saved Yahoo chart API response for an iShares ACWI ETF on Milan, used by Yahoo source tests
- `IUSQ.DE.json`: Saved Yahoo chart API response for an iShares ACWI ETF on Xetra, used by Yahoo source tests
- `OTGLF.json`: Saved Yahoo chart API response for CD Projekt OTC ordinary shares in USD, used by Yahoo source tests
- `OTGLY.json`: Saved Yahoo chart API response for CD Projekt OTC ADR in USD, used by Yahoo source tests
- `SSAC.AS.json`: Saved Yahoo chart API response for an iShares ACWI ETF on Amsterdam, used by Yahoo source tests
- `SSAC.L.json`: Saved Yahoo chart API response for an iShares ACWI ETF on London in GBp, used by Yahoo source tests
- `SSAC.SW.json`: Saved Yahoo chart API response for an iShares ACWI ETF on Zurich in CHF, used by Yahoo source tests
- `USDPLN=X.json`: Saved Yahoo chart API response for the USD to PLN rate, used by Yahoo source tests

## tests/fixtures/yahoo/history/

- `BP.L.json`: Saved Yahoo chart response with daily closes for BP.L in GBp, used by history tests

## tests/fixtures/yahoo/search/

- `GC=F.json`: Saved Yahoo search response for the Gold futures query, used by search tests
- `IE00B6R52259.json`: Saved Yahoo search response for an ISIN query, used by instrument search tests
- `bitcoin.json`: Saved Yahoo search response for the bitcoin query, used by search tests
- `cd_projekt.json`: Saved Yahoo search response for the name query CD Projekt, used by instrument search tests
- `iShares_MSCI_All_Country_World_UCITS_ETF_USD_Acc.json`: Saved Yahoo search response for an iShares ACWI ETF name query, used by instrument search tests
