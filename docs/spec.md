# Specification — Personal Investment Tracker

Status: agreed with the product owner on 2026-10-08 (design interview Q1–Q55). Vocabulary: see `CONTEXT.md`. Key decisions: `docs/adr/`.

## 1. Goal and scope

Re-implement the inwestomat.eu "Portfolio tracker" Google Sheet (v2.0.1, 01.07.2026; source copy and Apps Script in `reference/`, git-ignored) as a local desktop application with the **same functionality and calculation logic** and a better UI (forms, validation, filtering), then extend it beyond the sheet.

- Single user, local Windows PC, no login (Q1, Q8, Q29). Architecture must allow a later move to multiple users / a server (ADR-0001).
- UI in Polish; code, DB names and technical docs in English (Q6).
- Spreadsheet bugs are fixed, not replicated; every fix that changes a number is a documented deviation (Q33, ADR-0004).
- Not needed: spreadsheet version check, migration between sheet versions, Apps Script triggers (Q37).

## 2. Architecture (Q13, Q26, Q10)

- Python 3.14, **NiceGUI** in native window mode, started from a desktop shortcut.
- **SQLite** via SQLAlchemy with schema migrations; DB file in the user's app-data folder, outside the repo.
- **Domain core**: pure Python package (no UI/DB imports) holding FIFO, valuation, cash, bonds, returns, benchmarks and tax logic. UI and persistence are thin layers around it.
- **Price Sources** and **Importers** are plug-in modules behind common interfaces.
- Automatic DB backup at every start, keeping the last 30 copies. Export of transactions to CSV and XLSX.
- Prices refresh at start (if older than the last market close) and on a "Odśwież" button, in the background; status and errors shown on the Dashboard (Q24).

## 3. Data model

### 3.1 Accounts (Q14, Q48, Q49)
- Managed list (not free text). Fields: name, broker name, Account Type, Cash Currencies (e.g. PLN only, or PLN+USD), optional FX Conversion Fee % (e.g. XTB 0.5%; empty for most accounts), flag "exclude FX result from Dashboard P&L", active/inactive.
- Account Types: Regular, IKE, IKZE, OIPE, PPK, OKI, Deposit/Savings. Each type maps to a **Tax Regime** module:
  - Regular: 19% Belka per sale, reported in PIT-38.
  - IKE/OIPE: exempt on a qualifying withdrawal, otherwise tax on the whole gain.
  - IKZE: contributions deductible, 10% flat tax at withdrawal.
  - PPK: own rules.
  - **OKI: placeholder** — no calculation, UI note that rules will be added once the law is final. From the start the app keeps everything a future OKI rule might need: Transactions, daily Account value (from History), Deposits/Withdrawals.

### 3.2 Instruments (Q15, Q16, Q46, Q21)
- Catalog entity: name, Asset Class, quote currency, market, Source Symbol per Price Source, optional Manual Price.
- Physical metals: weight (oz or g) and Buyback Spread %. Primary value = spot × weight × (1 − spread); spot value shown as secondary (Q46).
- Asset Classes: user-editable list, seeded with the sheet's 12: Gotówka, Akcje polskie, Akcje zagraniczne, Obligacje skarbowe polskie, Obligacje skarbowe zagraniczne, Obligacje korporacyjne polskie, Obligacje korporacyjne zagraniczne, Metale i surowce, Kryptowaluty, Waluty, Inne, Multi-asset. Renaming must not require code changes.
- Multi-asset Split per Instrument; cannot be saved unless it sums to 100%. Buying an unconfigured Multi-asset Instrument opens the split dialog (Q41).
- Allocation Target % per Asset Class; warning (not block) when targets ≠ 100% (Q41).
- Currencies: base PLN; any NBP table-A currency. Base-currency change is designed for but not built (Q16).

### 3.3 Transactions (Q22, Q23, Q37, Q38, Q50)
Types: Deposit (Wpłata), Withdrawal (Wypłata), Buy (Zakup), Sell (Sprzedaż), Dividend/Interest (gross, withholding tax, net), Cost (Koszty), Split (X:Y), Currency Exchange (Wymiana walut), Cash Transfer, Security Transfer (keeps Lot dates and costs), DRIP.

Each Transaction stores:
- account, date, instrument, quantity, price (instrument currency), commission (any currency), nominal (Catalyst bonds), comment;
- **Actual Amount** (PLN that really moved; entered or derived from the user's rate) and **Tax Amount** (at NBP D-1) (Q38);
- FX Conversion Fee amount when an automatic conversion happened;
- **Origin**: manual / spreadsheet import / broker import, plus external id (e.g. XTB order number) and reconciliation date (Q52, Q53).

FX conversion on a PLN-only Account (Q49, Q50, Q50b, Q56, prototype verdict): conversion happens only when a Buy/Sell/Dividend is in a currency the Account does not hold.
- By default the form shows a rate field (`Kurs USD/PLN`, empty = NBP D-1); Actual Amount = quantity × price × rate ± commission.
- Below the commission, a checkbox "Prowizja <broker> (przewalutowanie X%)" appears **only on Accounts with an FX Conversion Fee configured**, **unchecked by default**. When checked, the user **must enter the PLN amount charged by the broker**; the app derives the effective rate and the fee and records the fee as a Cost (Dashboard "Prowizje i koszty"; deductible cost in PIT-38 for Regular accounts).
- On an Account with a matching Cash Currency the user chooses the payment source (foreign cash, or PLN with conversion). The form offers "exchange currency automatically" to create Currency Exchange + Buy in one go (Q19).

Validation at save time (Q36):
- Block: selling more than held on that Account at that date; Split before the first Buy or malformed ratio; missing NBP rate (never silently 0 PLN).
- Warn only: insufficient cash (allows entering history in any order) (Q19).

### 3.4 Bonds (Q17, Q34, Q45)
- Instrument = **Bond Series** in MF convention `TYPYMMRR` (type + maturity month + 2-digit maturity year, e.g. EDO bought 07.2025 → `EDO0735`). Each purchase is its own Lot with date, first-year rate, margin, quantity and Rollover flag/price.
- Supported: TOS, COI, EDO, ROS, ROD (as in sheet) plus ROR, DOR valued automatically.
- Rates: **MF-published rate is authoritative**; CPI(YoY, month = anniversary − 2) − 100 + margin, floored at 0, only for unpublished periods and flagged **Estimated**. Valuations show whether they rest on official or estimated rates.
- Valuation as sheet: linear accrual within a year; EDO/ROS/ROD compound annually; COI coupons paid out (base stays nominal) and tracked net of 19%; TOS fixed rate compounding.
- Extras: net value after early-redemption fee and Belka tax; calendar of coupon payments and maturities; sale picks a specific Lot (default oldest).
- Rollover price from the MF file (default 99.90).

### 3.5 FIFO and cash (Q20, Q31, Q32, ADR-0003)
- One lot engine for Portfolio, Sell Summary and PIT-38. FIFO only.
- Lot key: Account + Instrument. Same-day order: Split, Buy, Security Transfer, Sell, DRIP/Deposit.
- Buy fee capitalised into Lot cost; each Lot carries Actual cost and Tax cost (qty × price × NBP D-1 + fee in PLN).
- Splits rescale open Lots (qty × X/Y, unit price × Y/X); fees are not rescaled.
- Cash Balance per Account and Cash Currency; foreign cash held as Lots with PLN cost → FX result per Account, excludable by the Account flag. Commission paid in PLN is not counted in the foreign-cash quantity.
- Dividend attribution to sold pairs (Sell Summary): pro-rata by quantity held on the dividend date, with split-adjusted units.

## 4. Price sources (Q12, Q35, ADR-0005)

| Data | Source |
|---|---|
| GPW current (shares, NewConnect, ETF, bonds) | Bossa JSON API (bulk per category) |
| Foreign stocks/ETF, crypto, metals | Yahoo chart API (GBp → /100; crypto non-USD via USD cross) |
| GPW history, indices (WIG, sWIG80TR) | Stooq |
| Funds, PPK | analizy.pl API, fallback bankier.pl |
| Catalyst prices, accrued interest, nominal | gpwcatalyst.pl |
| IZ indexed nominal | gov.pl "współczynniki indeksacji" |
| FX (transactions, valuation, history) | NBP API table A |
| CPI | GUS CSV ("Analogiczny miesiąc poprzedniego roku = 100") |
| Retail bond rates, rollover price | MF XLS linked from gov.pl/web/finanse/obligacje-detaliczne1 |

Dropped: Google Finance, FT, Biznesradar scraping. Each source is a module with per-class fallback order configurable in settings. When all fail: last known price with its timestamp and a staleness warning; Manual Price always available. Historical prices and FX are cached locally (needed for History, ADR-0002).

### 4.1 Automatic valuation rules (grilling of #3 and #25)
- **Manual Price wins while set**; the automatic Quote is still fetched and shown beside it. Clearing the Manual Price returns the Instrument to automatic valuation. Bond Series keep their Manual Price with status "do etapu 3" until Etap 3 values them from MF data.
- **Source Symbols** are a list per Instrument (one per Price Source), entered in the Instrument dialog with a "Sprawdź" button that fetches one Quote (price, currency, date) and warns on a currency mismatch; saving is allowed when the check fails. Imported Instruments start without Source Symbols; an "Instrumenty bez wyceny" list leads through them.
- **Fallback Order** per Asset Class; an Instrument uses only the sources it has a Source Symbol for, in that order, with no per-Instrument override. Defaults: Akcje polskie Bossa → Yahoo; Akcje zagraniczne Yahoo → Bossa; Obligacje korporacyjne polskie Bossa; Obligacje skarbowe/korporacyjne zagraniczne, Metale i surowce, Kryptowaluty Yahoo; Multi-asset, Inne and classes the user adds analizy.pl → bankier.pl → Yahoo → Bossa; Gotówka, Waluty, Obligacje skarbowe polskie none. Stooq serves history and indices only (#33), through the user's personal Stooq API key entered in Ustawienia; History asks for an Instrument's Quotes or a currency's NBP Rates in a date range and only days not fetched yet are fetched, up to yesterday.
- **Currency**: a source module returns the price in the Instrument's quote currency (GBp ÷ 100, crypto via USD cross) or an error; a mismatch is shown, never converted silently. Foreign Positions are valued at the latest NBP Rate.
- **Quotes**: one table of daily Quotes (Instrument, day, price, Price Source, fetch time); the current price is the newest Quote, a same-day refresh overwrites it, and History (Etap 4) fills older days into the same table.
- **Refresh**: in the background at start-up when the last successful refresh was before the most recent weekday close, and on demand from the header; only Instruments with an open Position are fetched. A price is **Stale** only when the latest attempt failed in every source; the Quote date is always shown, so no exchange calendar is needed.
- **Status**: the header shows "Wyceny: <time>" with a refresh button, red with the number of errors, listing failing Instruments and reasons; each Portfolio Position shows the Quote date and a badge (ręczna, nieaktualna, bez źródła, do etapu 3).
- **Physical metals**: optional metal weight per unit in grams (exact decimal, 31.1034768 g/oz) and Buyback Spread %; value = spot (USD/oz) × weight × (1 − spread) at the NBP Rate, spot shown alongside.
- **ISIN lookup (#25)**: Instruments get an optional, non-unique ISIN (each listing is its own Instrument). One search field "Szukaj (ISIN, nazwa lub symbol)" in the Instrument dialog, on create and edit, prefilled with the name of an Instrument without Source Symbols; it queries Yahoo search behind a swappable module, and a chosen result fills only empty fields (ISIN, quote currency, market, Yahoo and Bossa Source Symbols). Polish funds stay manual. TER, Distribution Policy and domicile are user-entered Instrument fields shown in the Portfolio; scraping them (e.g. justETF) is out of scope under ADR-0005.

## 5. Screens (tabs)

Shell (UI prototype verdict, branch `prototype/ui-shell`, issue #1): **left navigation menu**, Dashboard as tiles and cards, **"+" floating button** opening the transaction dialog. Number format everywhere: Polish (decimal comma, non-breaking thousand separators and before "zł"/"%"), produced by one shared formatter; amounts never wrap.

**View Scope** (Q61–Q64, inspired by MyFund): sub-portfolios are Accounts (no extra grouping level). A scope switcher in the header, visible on every tab, offers **Total** first, then Accounts sorted by value descending, each with value, share-of-total bar and daily change; inactive Accounts hidden behind "pokaż nieaktywne". Every tab (sums, charts, Portfolio, Transakcje, Wyniki, Strategia, Benchmarki) follows the scope; the last scope is remembered. Breadcrumbs (Total › Account) return to Total. Transfers between Accounts do not change Net Deposits or XIRR in Total; in an Account scope they count as Deposit on the target and Withdrawal on the source.

**Period selector** shared by all charts and results: 1M, 3M, YTD, 1Y, 3Y, 5Y, since inception, custom; the "from" date is where returns start from (Q65.4).

- **Dashboard**: section **Strategia inwestycyjna** (Allocation Targets per Asset Class, current share and value, difference in pp, shift to target allowing sales, "Planuję wpłacić" amount and its no-sale split per class, the deposit needed for full rebalancing without sales, link "Szczegóły" to the Strategie inwestycyjne tab); class values include Multi-asset Splits (Q58).
- **Dashboard** in Total scope also has: a **treemap of Accounts** (size = value, colour = result; click switches scope to that Account) and an **Account ranking** table (XIRR, TWR, P&L PLN, Net Deposits, costs; sortable, best/worst highlighted) (Q63). In every scope: a **profit-by-source waterfall** (price effect, FX effect, dividends, interest, commissions and costs, taxes) (Q65.1) and an **after-tax toggle** showing Regular-account results net of estimated Belka on unrealised gains (Q65.5).
- **Dashboard** also has: totals (account value, net deposits, open positions, cash, unrealised, realised, dividends, fees+costs, XIRR); per-Account table (up to any number of Accounts) with FX-exclusion flag; currency exposure **per currency** (Q40); price refresh status/errors. 9 charts from the sheet: dividends by year/account, currency exposure doughnut, Asset Class share over time (switchable month/quarter/half-year/year), Account values, allocation, value vs net deposits, P&L, XIRR, drawdown — each with date range and Account filter (Q43).
- **Wyniki** (new, Q39, Q39b): XIRR and TWR; drawdown on TWR; real (CPI-adjusted) return; YTD / 1y / 3y / since-inception per portfolio and per Account; max drawdown and recovery days; annualised volatility of daily TWR.
- **Strategie inwestycyjne** (Q58, Q60): the same class rows as the Dashboard section, each expandable to Instrument Targets within the class (% of the class, may include instruments not held yet, added from the catalog). A planned deposit is split class → instrument without selling, filling the most under-target items first ("water-filling"). A class with no Instrument Targets splits its amount proportionally to current values; Instrument Targets that do not sum to 100% block the split with a warning.
  - **Total and Account strategies** (Q66): Total has its own Investment Strategy (e.g. 50% bonds across all wealth); each Account may optionally have its own (e.g. IKE: 50% CSPX, 50% ACWI). An Account without one shows its structure without rebalancing. In Total scope the planned-deposit split also suggests **on which Account** to buy each missing class (an Account whose strategy or holdings include that class).
  - **Tolerance bands** (Q65.3): per target a ±pp band; rows coloured green/yellow/red; an in-app notice after price refresh when a class leaves its band.
- **Portfolio** (**read-only**): open Positions as expandable cards per Account (total and P&L in the header): quantity, average price, cost PLN, average FX, current FX, price, daily change, value PLN, P&L % in instrument currency and in PLN, P&L PLN; Lot details.
- **Transakcje**: ledger with filters; forms per transaction type in a dialog; clicking a Transaction opens the same dialog for **editing or deleting** it (deletion confirmed; edits/deletes revalidated so no later Sell loses coverage).
- **Obligacje**: Lots of retail bonds with rate per year (official/estimated), current value, net value after early redemption and tax, coupons, calendar.
- **Multi-asset**, **Benchmarki**, **Sprzedaż Podsumowanie**, **Ustawienia** (Accounts, Asset Classes, Instruments and Source Symbols, sources order, limits), technical views (FX rates, prices with timestamps, CPI).

## 6. History, returns and benchmarks (Q11, Q28, Q39, Q42, Q44)
- History recomputed daily from the first Transaction (ADR-0002): value per Asset Class, total, Net Deposits, XIRR, P&L, TWR, drawdown.
- XIRR: Deposits negative, Withdrawals positive, final value at the end date (no row limit).
- Benchmarks may carry a "+x pp/year" offset (e.g. CPI + 3 pp) and may be another Account (Q65.13).
- Benchmarks: any catalog Instrument or CPI; every Deposit/Withdrawal "invested" into the benchmark on its date at its PLN price; CPI accrues monthly inflation spread evenly across days; per portfolio or per Account; no fees/taxes. Defaults: CPI, LON:ACWI, LON:CSPX, AMS:V80A, WSE:WIG, WSE:SWIG80TR.

## 7. Import and verification (Q3, Q25, Q42, Q51–Q53)
- Importer framework: parse file → preview with Instrument/Account mapping (unknown tickers resolved by the user) → duplicate detection → commit. Duplicates: same external id skipped; otherwise similar Transaction (Account, date, Instrument, quantity, ~amount) prompts the user.
- Stage 1 importer: `reference/Newest portfolio.xlsx` (one-time). Ticker mapping from sheet formats (`EXCH:SYM`, Biznesradar, `EDO-DDMMYY` → Bond Series, `Waluty_<CUR>` → foreign cash).
- **Parity tests**: the sheet's transactions with prices/FX frozen at export date; compare Portfolio, Dashboard totals, FIFO, XIRR and bonds within 0.01 PLN; each difference explained or recorded as a deviation. Stored Historia compared day by day for large discrepancies only. Fixtures stay in `reference/` (git-ignored).
- Stage 6: **XTB importer** (xStation account-history XLSX) and **Reconciliation** view: pair sheet vs XTB Transactions (Account, Instrument, type, quantity, date ±3 days); lists of differing pairs, sheet-only, XTB-only; per-pair or bulk "take XTB" / "keep mine"; XTB is the source of truth for XTB Accounts by default.

## 8. Tax and limits (Q18, Q47) — stage 6
- PIT-38 summary (revenue, costs, income) and foreign dividends (PIT-38 + PIT/ZG) from Tax Amounts, excluding tax-wrapped Accounts per their Tax Regime.
- IKE/IKZE/OIPE annual contribution limits (entered in settings, 2026 seeded) with progress bar and over-limit warning.
- OKI Tax Regime implemented once the law is final.

## 9. Known spreadsheet bugs to fix (documented deviations)
1. Yahoo FX backup stores the whole result array instead of the rate.
2. Google Finance path never divides GBX by 100 (`toUpperCase` without `()`).
3. Missing NBP rate yields FX 0 → Total PLN 0 silently.
4. Price-fetch timeout `return` inside `forEach` does not stop the loop.
5. Biznesradar bulk takes the first 3 chars as ticker; `WSE:` prefix compared unstripped.
6. FT map STO→OSL; Yahoo suffix map missing many exchanges.
7. Sell Summary FIFO diverges from Portfolio FIFO (DRIP ignored, case-sensitive tickers, date-only sort, split-scaled fees, mixed split units for dividends, matches later buys, silent oversell truncation, over-broad post-sale dividend rule).
8. Auto currency rows include PLN commission in foreign quantity.
9. Bond ticker collisions (same type and day); sale reduces only the first matching row; unrounded costs.
10. MF rate parser rounds rates > 1 to whole percent (6.80 → 7%).
11. ROD years 11–12 have no formulas; Obligacje rate update starts at row 2 while data starts at row 3.
12. Dashboard XIRR limited to Transakcje rows 2–61.
13. History freezes XIRR/P&L/drawdown at write time; monthly summary keys months without the year.
14. Off-by-one in currency dropdown; name formula frozen; only first space removed from tickers.
15. Multi-asset existence checked on raw instead of normalised ticker.
16. Raw-value drawdown distorted by deposits (replaced by TWR-based drawdown).

## 10. Delivery plan (Q5, Q54)

| Stage | Scope | Outcome |
|---|---|---|
| 0 Foundation | Project skeleton, NiceGUI shell with tabs, DB + migrations, backups, desktop shortcut | Empty app with tabs |
| 1 Transactions & Portfolio | Accounts (incl. OKI, FX fee), Instruments, Asset Classes, all transaction types with forms and validation, NBP rates, FIFO engine, cash, Portfolio with Manual Prices, importer framework + spreadsheet import, parity tests, CSV/XLSX export | Replace the sheet for bookkeeping |
| 2 Automatic prices | Slices (§4.1): 2a Price Source interface, Quotes, refresh, status and Yahoo; 2b Bossa; 2c analizy.pl and bankier.pl; 2d Stooq history and indices; 2e physical metals with Buyback Spread; ISIN lookup and fund details (#25) after 2a | Automatic valuation |
| 3 Bonds | MF file, GUS CPI, gpwcatalyst.pl (Catalyst prices, accrued interest, nominal), gov.pl IZ indexed nominal, Bond Series and Lots, sheet-parity valuation, ROR/DOR, net value, calendar, sale and Rollover | Obligacje tab |
| 4 Dashboard, History, Results | View Scope switcher (Total / Accounts) across all tabs, period selector, recomputed History, 11 charts, treemap and Account ranking, profit-by-source waterfall, after-tax toggle, Investment Strategy for Total and Accounts with tolerance bands (Dashboard section + Strategie inwestycyjne tab), Multi-asset, currency exposure, XIRR/TWR/drawdown, Wyniki tab, Historia parity check | Full Dashboard |
| 5 Reports | Benchmarks (with +pp offset, Account as benchmark), Sell Summary with closed-position statistics (win rate, holding time, best/worst), passive-income calendar (dividends and bond interest, received and forecast, monthly income goal) | Full parity with sheet v2.0.1 |
| 6 Beyond the sheet | PIT-38 / PIT/ZG with year-end tax-loss optimiser, contribution limits, XTB importer + Reconciliation, investment goal / FIRE per scope, recurring transactions (drafts to confirm), Account comparison mode, .exe installer, OKI tax when law is final. Parked ideas: virtual portfolio, net worth with liabilities, tags, price alerts, portfolio health score | Extensions |
