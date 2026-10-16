# Backlog

The local stand-in for GitHub Issues while the account was suspended (2026-10-12 to 2026-10-16); its open items are now GitHub issues (#91–#103), the source of truth from here on. Each stage follows `docs/spec.md` section 10; the details sit in the spec sections named beside each item. GitHub numbers (`#n`) refer to issues; the `L-n` ids are the local ones from the suspension.

Mark an item done with `[x]` and the merge commit or branch; new work goes to GitHub Issues.

## Done

- **Stage 0, Foundation**: skeleton, NiceGUI shell, database and migrations, backups, desktop shortcut.
- **Stage 1, Transactions and Portfolio (#2)**: #10–#22.
- **Stage 2, Automatic prices (#3)**: #25, #30–#34, #36–#42, #56–#60; also #63 and #64.
- **Stage 4, Dashboard, History, Results (#5)**: #68–#76, #78–#81, #84, #86, #89. Its spec 10 scope looks covered; check #5 for open sub-issues once GitHub is back.

## Stage 3, Bonds (#4), next

Decided in the grilling of 2026-10-12: `docs/spec.md` 3.4.1 and ADR-0007. Slices in this order:

- [x] L-1 Sources: the MF file (gov.pl), GUS CPI and the NBP reference rate history; check their formats first, then parsers on fixtures and SQLite caches, fetched with the price refresh at most once a day, failures in the header status. Branch `feat/bond-sources`.
- [x] L-2 Bond Series with their rates (first-year rate, margin, each period's) from the MF file, correctable by hand; the "+" dialog's bond mode (type and date give the Series, price 100 or the Rollover price with "z rolowania"); a migration clearing the imported Manual Prices; the sheet import stops setting one. Branch `feat/bond-sources`.
- [x] L-3 EDO valuation by the MF issue letters (per bond, MF rounding), with Estimated and Forecast Rates and their labels, in the Portfolio, Dashboard and History; unit tests on issue-letter examples and the parity test against the sheet's Obligacje tab (0.01 PLN per bond); drop the bond deviation of the Historia parity test. Branch `feat/bond-sources`.
- [x] L-4 Obligacje tab: Series expanding to Lots, gross and net value (fee and the Account's Tax Regime), the after-tax toggle. Branch `feat/bond-sources`.
- [x] L-5 Early Redemption: a Sell of a Bond Series picks its Lot (ADR-0007), prefilled with the value, the fee (built-in fee table) and the tax. Branch `feat/bond-sources`.
- [x] L-6 Maturity and Rollover as Drafts: the "Do zatwierdzenia" list, the header count, "roluj do…".
- [x] L-7 ROS, ROD, TOS, OTS. An OTS redeemed early pays no fee but loses its interest, so its Net Value before maturity is the nominal (the forfeited interest counts as its fee).
- [x] L-8 COI, ROR, DOR: coupons as Drafts (interest Dividends with Belka withheld).
- [x] L-9 Calendar of coupons, anniversaries and maturities (next 12 months) in the Obligacje tab.
- [x] L-10 Real return in Wyniki (TWR adjusted by GUS CPI). Branch `feat/bond-sources`.
- [x] L-11 Bond parity with the sheet across all held types (once L-7 and L-8 are in): every row of the tab (only EDO held), and each type the sheet values against its formulas. Branch `feat/bond-sources`.

Outside Stage 3, later:

- [x] L-23 gpwcatalyst.pl: Catalyst prices, accrued interest and nominal; Bossa's percent of nominal becomes a price (spec 4.2). Branch `feat/bond-sources`.
- [x] L-24 gov.pl IZ indexed nominal (spec 4.2). Branch `feat/bond-sources`.

## Stage 5, Reports

- [x] #91 (L-12) Benchmarks: any Instrument or CPI, Deposits and Withdrawals invested on their dates, a "+x pp/year" offset, an Account as a benchmark, the defaults (spec 6).
- [x] #92 (L-13) Sell Summary with closed-position statistics: win rate, holding time, best and worst (spec 10).
- [x] #93 (L-14) Passive-income calendar: Dividends and bond interest, received and forecast, monthly income goal (spec 10).

## Stage 6, Beyond the sheet

- [ ] #94 (L-15) PIT-38 and PIT/ZG summary with a year-end tax-loss optimiser (spec 8).
- [ ] #95 (L-16) IKE/IKZE/OIPE contribution limits with progress and an over-limit warning (spec 8).
- [x] L-17 XTB importer and the Reconciliation view (spec 7). Branch `feat/bond-sources`.
- [ ] #96 (L-18) Investment goal / FIRE per scope.
- [ ] #97 (L-19) Recurring transactions as drafts to confirm.
- [ ] #98 (L-20) Account comparison mode.
- [ ] #99 (L-21) .exe installer.
- [ ] #100 (L-22) OKI Tax Regime once the law is final (spec 8).

Parked ideas: virtual portfolio, net worth with liabilities, tags, price alerts, portfolio health score.

## Loose items

Bugs and small ideas that belong to no stage go here.

- [x] #101 (L-25) History without Stooq: no Stooq API key can be had (2026-10-12), so History uses Yahoo only. Done with analizy.pl only, the Bossa archive being gone (spec 4). Only if gaps hurt: add analizy.pl quotation history (funds, PPK) and/or the Bossa EOD archive `mstall.zip` (GPW, indices such as WIG) as keyless history sources (spec 4).
- [x] #102 (L-26) Past retail treasury bonds by Series name: in the "+" dialog's bond mode, let the user type or pick a Series (e.g. `EDO0827`, `COI1125`) instead of only the one the type and purchase date give, so older purchases can be entered. The MF file already holds the past Series (EDO from EDO1014, COI from COI1003, OTS, ROS, ROD, TOS, ROR, DOR all theirs), so valuation needs no new data: list the type's Series from the MF copy (searchable, newest first), check the purchase date against the Series' sale window (`SeriesTerms.sale_start`/`sale_end`; outside it a warning, a Rollover purchase may fall a few days later) and take the price from it (100 zł or its Rollover price). Check whether the MF file has the types no longer sold (e.g. DOS, TZ, CZL); without their terms such a Series is created with no rate and shows "brak oprocentowania" until corrected by hand (spec 3.4.1).
- [x] L-27 Excel-like filters and sorting in the Transakcje tab: each column header sorts (date newest or oldest first by its arrow, the default newest) and filters: Account, Transaction Type and Instrument as multi-choice lists of the values present, the amount as a range (od–do, on the Actual Amount, read with `parse_number`), the date as a range, and the comment by contained text (ignoring case). Filters combine with the View Scope, show as active on their headers with one "wyczyść filtry", and the export buttons export the filtered list.
- [ ] #116 (L-29) Podsumowanie sprzedaży table overlaps: the Instrument, Account and date cells run into each other (e.g. "PZU Etf Msci World" over "PKO Investment…" and the purchase date). `ui/sale_summary.py` sets `whitespace-nowrap` on every row of a grid whose columns have fixed minimum widths, so long names spill past their column. Let the Instrument and Account wrap within wider columns, keep the dates and numbers on one line, and right-align the number headers with their values.
- [ ] #117 (L-30) Ustawienia > Limity wpłat is hard to read: the IKZE field's hint ("Przy działalności gospodarczej: …") overlaps "wpłacono …" under it, because a Quasar hint is one line high and wraps to two; the description above the rows and the OIPE column are also cut off on a narrow window. Show the self-employed limit as a label of its own under "wpłacono", let the three columns share the row (and wrap their notes) instead of overflowing it.
- [ ] #118 (L-31) Transaction dialog order: choose the Account first, then the Transaction Type (now Typ comes first). The Account field stands out from the rest (a light blue background in the app's theme, the name in bold) to show that the type's fields, the Cash Currencies on offer and the bond mode all follow from it.
- [ ] #119 (L-32) Foreign-currency cash in the dialog for every Transaction an Account with several Cash Currencies (e.g. PLN and USD) takes: deposit USD, withdraw USD, buy and sell in USD, so nothing has to be converted by hand. Partly there already: Buy, Sell and Dividend offer "Płatność: gotówka USD / PLN z przewalutowaniem", a Cost and interest take a currency, and a Withdrawal may be in a foreign currency in the domain; but the dialog only lists Accounts holding PLN and a Deposit is PLN only. Decided 2026-10-16: a foreign Deposit or Withdrawal counts in PLN (Net Contribution, Contribution Limits) at the NBP Rate D-1, which the user may override with a rate of their own.
- [ ] #120 (L-33) Quantity from a PLN amount: buying a foreign-currency Instrument (e.g. Bitcoin in USD) with PLN, the user types the PLN amount to spend and the dialog converts it at the rate of the date and proposes the quantity to enter (amount ÷ rate ÷ price), which the user may still change. Decided 2026-10-16: the rate is the user's `fx_rate` if typed, else the NBP Rate D-1, less the Account's FX Conversion Fee if it has one; the commission comes out of the amount; the quantity rounds down, to whole units, or to 8 decimals for crypto. Still open: how other fractional Instruments (fractional shares) are marked.
- [x] #103 (L-28) Deleting an Account and no "+" in Ustawienia: the Account dialog in Ustawienia > Konta gets a "Usuń konto" button (editing only, with a confirmation naming the Account) that deletes it; an Account still named by Transactions (its own or as a Transfer's target), a Strategy or the XTB account mapping is refused with a Polish message saying what holds it (deactivating stays the way to hide it). The floating "+" (`add-transaction`) is not shown on the Ustawienia tab.
