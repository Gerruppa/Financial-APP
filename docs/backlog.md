# Backlog

The local stand-in for GitHub Issues while the account is suspended (since 2026-10-12). Each stage follows `docs/spec.md` section 10; the details sit in the spec sections named beside each item. GitHub numbers (`#n`) refer to existing issues; local items get an `L-n` id until they can be moved to GitHub.

Mark an item done with `[x]` and the merge commit or branch. When GitHub is back, open an issue for each open `L-n` item and replace the id with its number.

## Done

- **Stage 0, Foundation**: skeleton, NiceGUI shell, database and migrations, backups, desktop shortcut.
- **Stage 1, Transactions and Portfolio (#2)**: #10–#22.
- **Stage 2, Automatic prices (#3)**: #25, #30–#34, #36–#42, #56–#60; also #63 and #64.
- **Stage 4, Dashboard, History, Results (#5)**: #68–#76, #78–#81, #84, #86, #89. Its spec 10 scope looks covered; check #5 for open sub-issues once GitHub is back.

## Stage 3, Bonds (#4), next

Decided in the grilling of 2026-10-12: `docs/spec.md` 3.4.1 and ADR-0007. Slices in this order:

- [x] L-1 Sources: the MF file (gov.pl), GUS CPI and the NBP reference rate history; check their formats first, then parsers on fixtures and SQLite caches, fetched with the price refresh at most once a day, failures in the header status. Branch `feat/bond-sources`.
- [ ] L-2 Bond Series with their rates (first-year rate, margin, each period's) from the MF file, correctable by hand; the "+" dialog's bond mode (type and date give the Series, price 100 or the Rollover price with "z rolowania"); a migration clearing the imported Manual Prices; the sheet import stops setting one.
- [ ] L-3 EDO valuation by the MF issue letters (per bond, MF rounding), with Estimated and Forecast Rates and their labels, in the Portfolio, Dashboard and History; unit tests on issue-letter examples and the parity test against the sheet's Obligacje tab (0.01 PLN per bond); drop the bond deviation of the Historia parity test.
- [ ] L-4 Obligacje tab: Series expanding to Lots, gross and net value (fee and the Account's Tax Regime), the after-tax toggle.
- [ ] L-5 Early Redemption: a Sell of a Bond Series picks its Lot (ADR-0007), prefilled with the value, the fee (built-in fee table) and the tax.
- [ ] L-6 Maturity and Rollover as Drafts: the "Do zatwierdzenia" list, the header count, "roluj do…".
- [ ] L-7 ROS, ROD, TOS, OTS.
- [ ] L-8 COI, ROR, DOR: coupons as Drafts (interest Dividends with Belka withheld).
- [ ] L-9 Calendar of coupons, anniversaries and maturities (next 12 months) in the Obligacje tab.
- [ ] L-10 Real return in Wyniki (TWR adjusted by GUS CPI).
- [ ] L-11 Bond parity with the sheet across all held types (once L-7 and L-8 are in).

Outside Stage 3, later:

- [ ] L-23 gpwcatalyst.pl: Catalyst prices, accrued interest and nominal; Bossa's percent of nominal becomes a price.
- [ ] L-24 gov.pl IZ indexed nominal.

## Stage 5, Reports

- [ ] L-12 Benchmarks: any Instrument or CPI, Deposits and Withdrawals invested on their dates, a "+x pp/year" offset, an Account as a benchmark, the defaults (spec 6).
- [ ] L-13 Sell Summary with closed-position statistics: win rate, holding time, best and worst (spec 10).
- [ ] L-14 Passive-income calendar: Dividends and bond interest, received and forecast, monthly income goal (spec 10).

## Stage 6, Beyond the sheet

- [ ] L-15 PIT-38 and PIT/ZG summary with a year-end tax-loss optimiser (spec 8).
- [ ] L-16 IKE/IKZE/OIPE contribution limits with progress and an over-limit warning (spec 8).
- [ ] L-17 XTB importer and the Reconciliation view (spec 7).
- [ ] L-18 Investment goal / FIRE per scope.
- [ ] L-19 Recurring transactions as drafts to confirm.
- [ ] L-20 Account comparison mode.
- [ ] L-21 .exe installer.
- [ ] L-22 OKI Tax Regime once the law is final (spec 8).

Parked ideas: virtual portfolio, net worth with liabilities, tags, price alerts, portfolio health score.

## Loose items

Bugs and small ideas that belong to no stage go here.
