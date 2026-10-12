# Project Filetree

_Auto-maintained by `/filetree:update`. Content hashes live in the sidecar `FILETREE.hash.json`; do not edit it by hand._

## (root)/

- `.filetree.json`: Filetree manifest config: manifest path, include/exclude filters, summary language, commit guard and self-only mode.
- `.gitignore`: Git ignore rules for the venv, caches, build output, the personal spreadsheet reference folder and graphify output.
- `CLAUDE.md`: Guidance for Claude Code: project state, module layout, environment commands and the domain rules for this repo.
- `CONTEXT.md`: Domain glossary defining the app's Polish-labelled terms (Accounts, Instruments, Transactions, Lots, Quotes) and terms to avoid.
- `GLOSSARY.md`: Polish-to-English index of glossary terms, mapping UI labels to CONTEXT.md definitions and sections
- `README.md`: User-facing setup guide: install steps, desktop shortcut creation, data location, backups and log file.
- `alembic.ini`: Alembic CLI configuration pointing migrations at the persistence package; the app runs them itself at start-up.
- `main.py`: Convenience script entry point that calls the app's main function to start the window.
- `pyproject.toml`: Package metadata, dependencies, console and GUI entry points, pytest, mypy and ruff settings.

## docs/

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

## docs/agents/

- `domain.md`: Agent instructions for reading CONTEXT.md and ADRs before exploring code and using the glossary's vocabulary.
- `issue-tracker.md`: Agent instructions for managing issues, PRs and wayfinder maps on GitHub with the gh CLI.
- `triage-labels.md`: Mapping of the five canonical triage roles to this repo's GitHub issue label names.

## scripts/

- `create_desktop_shortcut.ps1`: PowerShell script creating a Windows desktop shortcut that starts the console-less app window.

## src/financial_app/

- `__init__.py`: Empty package marker for the financial_app package.
- `__main__.py`: Module entry point so the package can be run with python -m financial_app, starting the app.
- `app.py`: Application start-up: attaches logging, backs up and migrates the database, then opens the NiceGUI window.

## src/financial_app/domain/

- `__init__.py`: Docstring marking the domain package as pure-Python calculations with no UI or database imports.
- `account_ranking.py`: Account ranking and treemap figures for the Total Dashboard: XIRR, TWR, P&L, Net Deposits and costs per Account, sorted with best and worst marked
- `accounts.py`: Account Types, their Tax Regime descriptions and validation of Account fields with Polish error messages.
- `charts.py`: Dashboard chart data from History and Transactions: value, profit, XIRR, class shares and dividends by year, per scope and period
- `currencies.py`: Currency code check and the NBP Rate value type, plus the error raised when a rate is missing.
- `dashboard.py`: Dashboard totals, Account table, currency exposure and allocation from Transactions, prices, NBP Rates and History, plus estimated tax and profit by source
- `export.py`: Builds the transaction export rows with columns, amounts, origin and comment, independent of file format.
- `formatting.py`: Polish number, amount and date formatting and parsing of typed input; the single formatter every screen uses.
- `history.py`: Tracks which days of Quote and NBP Rate history are cached, and computes the missing days to fetch.
- `instrument_search.py`: Instrument search result types, the swappable search protocol, and filling empty form fields from a chosen result.
- `instruments.py`: Instrument and Asset Class models, their validation, default Asset Classes, ISIN, metal, distribution policy and Multi-asset Split rules.
- `lots.py`: The single FIFO engine that opens and consumes Lots for Positions and foreign cash, raising uncovered-sale errors.
- `metrics.py`: Pure History metrics: XIRR, TWR, drawdowns, max drawdown, volatility and daily change per Total or Account
- `multi_asset.py`: Multi-asset Instruments held in the View Scope, with their PLN value and split value per Asset Class, largest first
- `periods.py`: Period presets and custom ranges for charts and results, with date calculation and text persistence
- `portfolio_history.py`: Computes daily Portfolio value and Net Deposits per Account and Asset Class from transactions and cached prices
- `prices.py`: Quote model, Price Source keys and names, and the per-Asset-Class Fallback Order deciding which sources to try.
- `profit_sources.py`: Splits the View Scope's result into price, FX, Dividends, interest, costs and taxes for the Dashboard waterfall
- `results.py`: Wyniki tab figures: period XIRR, TWR, drawdown, volatility and fixed-period returns per Total and Account, from History
- `spreadsheet_import.py`: Pure conversion of the user's Inwestomat Transakcje sheet rows into Transaction drafts, with fingerprints for re-import skipping.
- `strategy.py`: Investment Strategy rules: Allocation Targets with tolerance bands, Instrument Targets, and the water-filling split of the Planned Deposit
- `transactions.py`: Transaction types, drafts and builders for every kind, plus cash balances and cost and dividend totals per Account.
- `valuation.py`: Decides each Instrument's price and status from Manual Price or Quote, including metal spot conversion and badges.
- `view_scope.py`: View Scope logic: Total or one Account, its remembered setting, switcher entries and transaction filtering

## src/financial_app/persistence/

- `__init__.py`: Package marker for the SQLite and SQLAlchemy persistence layer.
- `accounts.py`: Saves and reads Accounts, enforcing case-insensitive unique names and cash currency rows.
- `backup.py`: Copies the database to the backups folder at each start and keeps only the newest copies.
- `db.py`: Opens the SQLite engine and applies pending Alembic migrations at start-up.
- `history.py`: Reads and writes cached Stooq Quote history and NBP Rate history, with the cover of fetched days.
- `instruments.py`: Saves and reads Asset Classes and Instruments, and deletes Instrument data including its Quotes and failures.
- `models.py`: SQLAlchemy ORM models describing the database tables; schema changes go through migrations
- `nbp_rates.py`: SQLite cache of NBP Rates keyed by currency and day
- `paths.py`: Resolves the user's data, backup and log folders, kept outside the repository
- `quotes.py`: Saves and reads daily Instrument Quotes and the last price refresh status
- `reset.py`: Clears all portfolio data after a backup and restores default Asset Classes
- `settings.py`: Reads and writes text application settings by key in the app_settings table
- `strategies.py`: Reads and saves Investment Strategies for Total and each Account, with their Allocation and Instrument Targets
- `transactions.py`: Saves, edits, deletes and lists Transactions, replaying positions to block invalid changes

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

## src/financial_app/sources/

- `__init__.py`: Package marker describing the external price sources package
- `analizy.py`: Fund and PPK Quotes and fund search through the undocumented analizy.pl API, a price source and an Instrument lookup.
- `bankier.py`: Fetches fund and PPK Quotes from bankier.pl pages as the fallback price source
- `bossa.py`: Fetches GPW, NewConnect, ETF and bond Quotes in PLN from the Bossa JSON API
- `current_prices.py`: Today's valuation inputs shared by the Portfolio and the Dashboard: Instrument prices and NBP Rates from the last business day before today, each currency fetched once
- `dashboard.py`: Computes today's Dashboard of a View Scope from the database, shared by the Dashboard and the Investment Strategy
- `export.py`: Writes the Transactions list to CSV and XLSX files for export
- `history.py`: Returns an Instrument's Quotes in a date range, fetching missing days from Stooq into cache
- `nbp.py`: Gets NBP exchange rates from the NBP API through the local cache
- `portfolio_history.py`: Fetches History prices and NBP Rates into cache and computes daily values, cached until invalidated
- `prices.py`: Refreshes held Instruments' Quotes from price sources in fallback order and records failures
- `spreadsheet.py`: Previews and imports Transactions and Instruments from the user's Inwestomat spreadsheet
- `stooq.py`: Stooq history source for GPW stocks and indices; fetches daily closes via CSV with API key and browser proof-of-work check
- `yahoo.py`: Yahoo Finance source for current quotes and Instrument search; converts GBp pence and parses chart and search responses

## src/financial_app/ui/

- `__init__.py`: Package marker for the NiceGUI user interface layer, a thin layer over domain and persistence
- `account_ranking.py`: Total Dashboard's Accounts treemap and sortable Account ranking; clicking a tile switches the View Scope to that Account
- `accounts.py`: Ustawienia Konta card: lists Accounts and opens the add and edit dialog
- `charts.py`: Dashboard's nine ECharts charts plus the profit-by-source waterfall, following the View Scope and period
- `dashboard.py`: Dashboard tab UI: totals, price status, Account table, exposure, charts, Account treemap and ranking, and the after-tax toggle
- `dialogs.py`: Draggable dialog support with no backdrop, so the screen behind stays readable
- `fund_details.py`: Builds the short fund detail texts (TER, Distribution Policy, domicile) shared by Instrument list and Portfolio
- `history.py`: Shared per-database History window state: background fetch, progress and failure status, cached days
- `import_sheet.py`: Ustawienia import section that previews the Transakcje spreadsheet and saves it only after user decisions
- `instruments.py`: Ustawienia Klasy aktywów and Instrumenty cards: editable Asset Classes and the Instrument catalog with its dialog
- `multi_asset.py`: Multi-asset tab and split editor: edits an Instrument's Multi-asset Split and lists held Multi-asset Instruments by Asset Class
- `periods.py`: Period selector UI: preset buttons and custom range inputs, remembered per user and redrawing listeners
- `portfolio.py`: Read-only Portfolio tab: per-Account cards with cash balances, valued Positions, Lots, FX result and dividends
- `price_sources.py`: Ustawienia Źródła wycen card where the user stores the personal Stooq API key
- `reset.py`: Ustawienia Wyczyść dane card that clears the whole portfolio after a warning and typed confirmation
- `results.py`: Wyniki tab page: result tiles, drawdown chart and per-Account results table under the period selector
- `settings.py`: Builds the Ustawienia page by assembling its sections: Accounts, Asset Classes, Instruments, sources, import, reset
- `shell.py`: Main app window shell: left menu, header with refresh status and View Scope, and the transaction button
- `strategy.py`: Strategie inwestycyjne tab, Dashboard strategy section and post-refresh notice for classes outside their tolerance band
- `transactions.py`: Transakcje tab and transaction dialog for adding, editing and deleting all supported transaction types
- `unpriced.py`: Ustawienia Instrumenty bez wyceny card listing held Instruments lacking an automatic price, with reasons
- `view_scope.py`: View Scope header switcher and breadcrumbs, listing Accounts by value with share and daily change

## tests/

- `test_account_ranking_domain.py`: Tests Account ranking figures, sorting, best and worst marks and treemap tiles
- `test_account_ranking_ui.py`: Tests the Dashboard's Account treemap and ranking, profit waterfall and after-tax toggle
- `test_accounts_domain.py`: Tests Account Types, Tax Regime registry and AccountDraft validation rules
- `test_accounts_repository.py`: Tests saving, listing and editing Accounts in SQLite, including unique names
- `test_accounts_ui.py`: UI tests for Ustawienia Konta: adding, editing and deactivating Accounts without a browser
- `test_analizy_search.py`: Tests for analizy.pl fund and PPK search on saved, trimmed responses without network
- `test_analizy_source.py`: Tests the analizy.pl fund and PPK quote source against saved API responses
- `test_architecture.py`: Architecture test enforcing that the domain core does not import UI or database code
- `test_backup.py`: Tests database backup copies and the retention of the newest backups
- `test_bankier_source.py`: Tests the bankier.pl fund and PPK quote source against saved pages
- `test_bossa_source.py`: Tests the Bossa JSON API quote source against saved responses
- `test_charts_domain.py`: Unit tests for the Dashboard chart data: value, profit, XIRR, class shares and dividends by year
- `test_clear_data_repository.py`: Tests that clearing the portfolio removes user data and restores default Asset Classes
- `test_clear_data_ui.py`: UI tests for the Wyczyść dane confirmation flow in Ustawienia
- `test_conversion_fee_domain.py`: Domain tests for the broker FX Conversion Fee on foreign-currency Buys and Sells
- `test_conversion_fee_ui.py`: UI tests for the FX Conversion Fee and payment source in the transaction dialog
- `test_dashboard_charts_ui.py`: UI tests that the Dashboard's nine charts follow the View Scope and the period
- `test_dashboard_domain.py`: Tests the Dashboard domain totals, Account table and currency exposure
- `test_dashboard_ui.py`: UI tests for the Dashboard tab: totals, Account table, currency exposure and price status
- `test_database.py`: Checks that the ORM models and Alembic migrations stay in sync
- `test_dividends_domain.py`: Domain tests for Dividends, interest, Costs and DRIP calculations
- `test_dividends_repository.py`: Tests saving Dividends, Costs and DRIPs to SQLite
- `test_dividends_ui.py`: UI tests for Dividends, Costs and DRIP in the transaction dialog, Transakcje and Portfolio
- `test_export_domain.py`: Tests the export rows built for the Transakcje list across all Transaction types
- `test_export_files.py`: Tests the CSV and XLSX export files, including Polish characters and read-back
- `test_export_ui.py`: UI tests for the Transakcje export buttons saving CSV and XLSX files
- `test_fallback_order_ui.py`: UI tests for editing an Asset Class's Fallback Order in Ustawienia: showing, removing, adding, moving and saving sources.
- `test_foreign_cash_domain.py`: Domain tests for foreign cash Lots, Currency Exchange and FX result per Account
- `test_foreign_cash_repository.py`: Tests saving Currency Exchanges and foreign-cash Buys to SQLite
- `test_foreign_cash_ui.py`: End-to-end UI tests for foreign cash, Currency Exchange and FX result
- `test_foreign_trades_ui.py`: End-to-end UI tests for foreign-currency Buys and Sells using the NBP Rate
- `test_formatting.py`: Tests the Polish number, date and count formatting and typed-input parsing helpers
- `test_fund_details_ui.py`: UI tests for a fund's TER, Distribution Policy and domicile in the dialog and Portfolio
- `test_fx_effect_domain.py`: Tests the FX part of foreign Positions' results from the PLN and foreign costs of FIFO Lots
- `test_glossary.py`: Test that GLOSSARY.md lists exactly the terms defined in CONTEXT.md
- `test_history_domain.py`: Tests which days of a price history still need fetching given cached days
- `test_history_parity.py`: Parity test of History against the user's spreadsheet Historia tab at each month end, skipped without reference data
- `test_import_sheet_ui.py`: UI tests for the Ustawienia spreadsheet import: preview first, then save, on a synthetic workbook
- `test_instrument_search_domain.py`: Tests that a chosen Instrument search result fills only the empty Instrument form fields.
- `test_instrument_search_ui.py`: Tests searching an Instrument by ISIN, name or symbol in the Instrument dialog on saved Yahoo responses.
- `test_instruments_domain.py`: Tests Instrument and Asset Class validation rules, including fund and distribution policy fields.
- `test_instruments_repository.py`: Tests saving Asset Classes and Instruments in SQLite, including uniqueness and updates.
- `test_instruments_ui.py`: Tests the Klasy aktywów and Instrumenty sections of Ustawienia, run without a browser.
- `test_lots_domain.py`: Tests the FIFO Lot engine and the Positions it produces from Transactions.
- `test_metrics_domain.py`: Unit tests for History metrics: XIRR, TWR, drawdown and volatility per Total or Account
- `test_multi_asset_domain.py`: Tests Multi-asset Split rules in the domain: validation, class parts, History, Dashboard allocation and holdings
- `test_multi_asset_repository.py`: Tests saving Multi-asset Splits with their Instruments, Asset Class rules, and their removal on reset
- `test_multi_asset_ui.py`: UI tests for the Multi-asset split in the Instrument dialog, the split dialog after a buy, and the Multi-asset tab
- `test_nbp_rates.py`: Tests fetching and caching NBP D-1 rates from saved API responses, without the network.
- `test_paths.py`: Tests that the default data directory lies outside the repository and respects the override.
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
- `test_results_domain.py`: Tests for the Wyniki tab's period results and fixed-period rows per Total and Account
- `test_results_ui.py`: UI tests for the Wyniki tab: tiles, drawdown chart, results table and pending state
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
- `test_trades_ui.py`: Tests PLN Buys and Sells end to end through the transaction dialog, Transakcje list and Portfolio.
- `test_transaction_edit_ui.py`: UI tests for editing and deleting a Transaction from the Transakcje list, including blocked edits
- `test_transactions_domain.py`: Domain tests for Deposits, Withdrawals, trade amounts, validation and per-Account cash balances
- `test_transactions_repository.py`: Repository tests for saving, listing, editing and deleting Transactions in SQLite, with FIFO coverage checks
- `test_transactions_ui.py`: UI tests for Deposits and Withdrawals from the plus dialog, Transakcje list and Portfolio Cash Balance
- `test_unpriced_domain.py`: Domain tests for the Instrumenty bez wyceny list: which held Instruments lack an automatic price and why
- `test_unpriced_ui.py`: UI tests for the Instrumenty bez wyceny section in Ustawienia, including opening and fixing a symbol
- `test_valuation_domain.py`: Domain tests for Instrument price selection, PLN conversion, staleness badges and metal spot valuation
- `test_view_scope_domain.py`: Tests the View Scope domain: Total or one Account, its text setting, and the Accounts the switcher offers.
- `test_view_scope_ui.py`: UI tests for the View Scope switcher, breadcrumbs, scope-following tabs and the period selector.
- `test_windowless.py`: Tests that windowless launches redirect stdout and stderr to a log file while console launches stay untouched
- `test_yahoo_search.py`: Tests Yahoo Instrument search by ISIN and name on saved responses, with error handling
- `test_yahoo_source.py`: Tests Yahoo chart quotes on saved responses: currency, pence conversion, crypto rate and error messages

## tests/fixtures/analizy/

- `FTI022_A_USD.json`: Saved analizy.pl fund quotation response for a USD Franklin Technology fund, used by tests
- `FTI068_AH_EUR.json`: Saved analizy.pl API response for a EUR fund, used to test the analizy price source offline
- `PZU01.json`: Saved analizy.pl quotation response for the PZU Akcji KRAKOWIAK fund, used by tests
- `PZU60.json`: Saved analizy.pl API response for the PZU60 PPK fund in PLN, for offline price source tests

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

## tests/fixtures/nbp/

- `usd_2025-12-24_2026-01-06.json`: Saved NBP API response with USD mid rates for late December 2025, for offline NBP tests
- `usd_2026-03-24_2026-04-06.json`: Saved NBP API response with USD mid rates for late March 2026, for offline NBP tests

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
