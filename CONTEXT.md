# Personal Investment Tracker

A local application for tracking personal investment portfolios, one per User: the user records every transaction by hand (or imports it), and the app values holdings, computes results and prepares tax data. It re-implements the inwestomat.eu "Portfolio tracker" Google Sheet (v2.0.1). UI is Polish; code is English — each term below gives the Polish UI label in parentheses.

## Users

**User** (Użytkownik):
A person who uses the app, known by a pseudonym and kept apart from others by a password. Each User has their own portfolio — Accounts, Transactions, settings — and sees no other User's. Several Users may share one computer and switch between them. The password keeps others out of the app, not out of the files on disk.
_Avoid_: account, profile, login

## Accounts and instruments

**Account** (Konto):
A place where the user holds cash and positions, e.g. an IKE at a broker or a bank deposit. Has an Account Type, one or more Cash Currencies and an optional FX Conversion Fee.
_Avoid_: wallet, portfolio, platform, broker

**Account Type** (Typ konta):
The legal wrapper of an Account — Regular, IKE, IKZE, OIPE, PPK, OKI, Deposit, Bonds (a retail treasury bond register) or Other (assets held outside a financial institution, e.g. physical metals) — which determines its Tax Regime.
_Avoid_: account kind, wrapper

**Tax Regime** (Sposób opodatkowania):
The rules by which gains on an Account are taxed (e.g. 19% Belka per sale for Regular, exemption for IKE, Belka withheld by the issuer for Bonds, the 6-month rule for selling things for Other, not yet defined for OKI).
_Avoid_: tax mode, tax strategy

**Contribution Limit** (Limit wpłat):
The most that may be paid in a calendar year into the Accounts of one Account Type — IKE, IKZE or OIPE — taken together. Deposits into such an Account and Cash Transfers into it from an Account of another type count towards it; Withdrawals do not free it up.
_Avoid_: cap, allowance, quota

**Cash Currency** (Waluta rachunku):
A currency in which an Account can hold cash. An Account with only PLN converts every foreign-currency trade automatically; an Account without PLN pays everything, commissions included, from its foreign cash.
_Avoid_: sub-account, currency account

**FX Conversion Fee** (Opłata za przewalutowanie):
A percentage a broker adds to the market rate when it converts currency for a foreign-currency trade on a PLN Account (e.g. 0.5% at XTB). Applied per Transaction only when the user marks it; recorded as a Cost of the transaction.
_Avoid_: spread, FX commission

**Instrument** (Instrument):
Anything that can be held and priced: a stock, ETF, fund, bond series, metal, crypto pair or a manually priced asset. Has one Asset Class, a quote currency, an optional ISIN, a Source Symbol per Price Source and the number of decimal places its quantity may have (0 for whole units, up to 8 for crypto or fractional shares). Each listing is its own Instrument: the same ISIN on two exchanges or in two currencies gives two Instruments.
_Avoid_: ticker, security, asset, symbol

**Source Symbol** (Symbol w źródle):
The identifier of an Instrument in one Price Source (e.g. `PZU.WA` in Yahoo, `pzu` in Stooq).
_Avoid_: ticker

**Search Result** (Wynik wyszukiwania):
An instrument found in an external search service (Yahoo, analizy.pl) that the user does not hold as an Instrument yet: its name, ISIN when known, and its Listings. It becomes an Instrument only when the user saves one of its Listings as one.
_Avoid_: quote, notowanie

**Listing** (Linia notowań):
One market and quote currency a Search Result trades in, with the Source Symbols its prices come from (e.g. the same ETF on the LSE in USD and in GBP is two Listings). Saving a Listing makes it an Instrument; one held already is the Instrument with any of its Source Symbols.
_Avoid_: quote, notowanie, ticker

**Instrument Card** (Karta instrumentu):
The view of one Search Result, one of the user's Instruments or one Bond Series type: what it is, its recent price and returns, and the step that follows (add it as an Instrument, edit it, or buy the bond type).
_Avoid_: instrument page, profile, factsheet

**Fund Code** (Kod funduszu):
The code of a Polish fund or PPK shared by analizy.pl and bankier.pl (e.g. `PZU60`, `QRS32`), stored as the Instrument's analizy.pl Source Symbol. bankier.pl uses it whenever the Instrument has no bankier.pl Source Symbol of its own (needed only when the codes differ, e.g. a unit category). Foreign fund series (e.g. `FTI068_AH_EUR`) exist only in analizy.pl.
_Avoid_: fund ID, fund symbol

**Asset Class** (Klasa aktywów):
A user-editable category used for allocation, e.g. Akcje zagraniczne, Obligacje skarbowe polskie, Metale i surowce.
_Avoid_: category, asset type

**Multi-asset Split** (Podział Multi-asset):
The percentage breakdown of one Multi-asset Instrument across Asset Classes, summing to 100%.
_Avoid_: allocation, look-through

**View Scope** (Widok):
What a screen is computed for: **Total** (all Accounts) or a single Account. Accounts are the sub-portfolios; there is no grouping level between them and Total.
_Avoid_: sub-portfolio, portfolio group, filter

**View Profile** (Profil widoku):
Which Dashboard tiles, sections and charts and which tabs the window shows, set in Ustawienia under Wygląd i widoczność: **Podstawowy** (a few tiles, the Account table, the value and allocation charts, only the main tabs), **Pełny** (everything, the default) or **Własny** (any other choice). One for every View Scope; hiding changes only the view, never a calculation. Dashboard, Portfolio, Transakcje and Ustawienia are always in the menu, and a hidden tab still opens at its address.
_Avoid_: theme, layout mode

**Investment Strategy** (Strategia inwestycyjna):
The set of Allocation Targets, optionally refined by Instrument Targets inside each Asset Class. Total has one; each Account may optionally have its own.
_Avoid_: model portfolio, plan

**Allocation Target** (Cel %):
The desired share of an Asset Class in the whole portfolio, used for rebalancing.
_Avoid_: target weight

**Tolerance Band** (Pasmo tolerancji):
How far, in percentage points either way, an Asset Class may drift from its Allocation Target before it needs rebalancing. Within the band it shows green, up to twice the band yellow, beyond that red.
_Avoid_: threshold, corridor

**Instrument Target** (Cel w klasie):
The desired share of an Instrument within its Asset Class; may name an Instrument not held yet.
_Avoid_: sub-target, weight

**Planned Deposit** (Planowana wpłata):
An amount the user intends to invest, split across Asset Classes and Instruments toward the Investment Strategy without selling anything.
_Avoid_: contribution, top-up

**Buyback Spread** (Spread odkupu):
The percentage below spot price at which a dealer buys back a physical metal Instrument. Its value is spot × the unit's metal weight (entered in grams) × (1 − Buyback Spread). Once the metal weight is set, the Instrument's prices (Quotes and Manual Price) are the spot of a troy ounce.
_Avoid_: discount, haircut

## Transactions and holdings

**Transaction** (Transakcja):
One user-recorded event on an Account: Deposit, Withdrawal, Buy, Sell, Dividend, Cost, Split, Currency Exchange, Cash Transfer, Security Transfer or DRIP.
_Avoid_: operation, trade, entry

**Recurring Rule** (Reguła cykliczna):
A Deposit, Buy, Cost or Cash Transfer the user repeats on an Account (monthly, quarterly, half-yearly or yearly, on a day of the month), with its planned amount; a Buy of a Bond Series repeats its bond type, whichever month's Series it buys. Each of its occurrences due by today and not matched by a Transaction is a Draft; an occurrence can be skipped for good.
_Avoid_: standing order, schedule, subscription

**Term Deposit** (Lokata terminowa):
A bank deposit on an Account of the Deposit type: a principal in PLN from a start date for a term of months or days at an annual rate, its interest capitalised at maturity or every month, quarter, half-year or year. Each capitalisation period earns the capital × the rate × its actual days / 365, rounded to the grosz, less Belka rounded to the grosz; a period capitalised before maturity adds its net interest to the next period's capital. Each period ended and not paid by an interest Dividend is a Draft, and so is its maturity, ended or renewed from that day; a deposit broken before maturity forfeits the period running then.
_Avoid_: savings account, lokata (alone)

**Accrued Interest** (Narosłe odsetki):
The interest a Term Deposit has earned and not yet paid into the cash, net of Belka: the periods ended and not paid, and the running period's days so far. It counts in its Account's value, as cash.
_Avoid_: pending interest, unpaid interest

**Dividend** (Dywidenda / odsetki):
A payout of an Instrument, or interest (with or without an Instrument), recorded with its gross amount and the withholding tax taken at source, both in its own currency. The net amount goes into PLN cash (converted) or foreign cash of the same currency. A Bond Series' coupon is recorded as interest naming the Lot it was paid on.
_Avoid_: coupon, income

**DRIP** (DRIP):
A Dividend reinvested into more units of its Instrument: it opens a Lot costing the net amount and moves no cash.
_Avoid_: reinvestment, scrip

**Cost** (Koszty):
An amount the Account paid outside a trade, e.g. for keeping the Account: in PLN, or from foreign cash at the NBP Rate. Together with commissions and FX Conversion Fees it makes up the Account's commissions and costs.
_Avoid_: fee, charge

**Actual Amount** (Kwota rzeczywista):
The PLN amount that really moved on the Account for a Transaction, including fees and FX spread. Drives balances, valuation and returns.
_Avoid_: Total PLN, real value

**Tax Amount** (Kwota podatkowa):
The PLN amount of a Transaction recomputed at the NBP Rate, used only for tax reports.
_Avoid_: fiscal value

**NBP Rate** (Kurs NBP D-1):
The NBP table A mid rate from the last business day before the Transaction date.
_Avoid_: official rate, tax rate

**Origin** (Pochodzenie):
Where a Transaction came from: manual entry, spreadsheet import or broker import.
_Avoid_: source

**Lot** (Partia):
A quantity of one Instrument (or foreign cash) acquired in one Transaction, carrying its own Actual and Tax cost. Sells consume Lots oldest-first (FIFO).
_Avoid_: tranche, batch

**Position** (Pozycja):
All open Lots of one Instrument on one Account.
_Avoid_: holding

**Cash Balance** (Saldo gotówki):
Cash held on an Account in one Cash Currency. Foreign cash is held as Lots so FX results can be measured.
_Avoid_: cash position

**Manual Price** (Cena ręczna):
A price the user enters for an Instrument. While it is set it wins over every Price Source; clearing it returns the Instrument to automatic valuation.
_Avoid_: override, custom quote

**Price Source** (Źródło wycen):
An external provider of quotes, FX rates, CPI or bond data (e.g. Bossa, Yahoo, NBP, MF).
_Avoid_: provider, feed, API

**Quote** (Notowanie):
The price of an Instrument on one day, in its quote currency, as given by one Price Source. An Instrument's current price is its newest Quote; older Quotes make up its price history.
_Avoid_: price point, tick, rate

**Fallback Order** (Kolejność źródeł):
The ordered list of Price Sources tried for an Asset Class. An Instrument uses only the sources it has a Source Symbol for (bankier.pl also through the Fund Code), in that order; with none it has no automatic valuation. The Instrument dialog shows the symbol fields in this order and folds the other sources away.
_Avoid_: priority, source chain

**Stale Price** (Nieaktualna cena):
The last known Quote of an Instrument, still used for valuation, after the latest refresh failed for it in every Price Source.
_Avoid_: old price, cached price

**Successful Refresh** (Udane odświeżenie):
A refresh of the Quotes in which not every Instrument fetched failed (one with nothing to fetch counts too). At start-up the app refreshes when the last Successful Refresh was before the most recent weekday session close (17:30), so a start with no network tries again next time.
_Avoid_: last update, sync

**Distribution Policy** (Polityka dywidendowa):
Whether a fund pays out its income (Dystrybucja) or reinvests it (Akumulacja). Entered by the user, like the fund's TER and domicile.
_Avoid_: dividend type

## Bonds

**Bond Series** (Seria obligacji):
A Polish retail treasury bond issue identified by type, maturity month and year, e.g. `EDO0735`. It is an Instrument, created on its first purchase from the type and purchase date, and carries the rates (first-year rate, margin, each period's rate) from the MF file, which the user may correct by hand; each purchase of it is a separate Lot earning from its own date.
_Avoid_: bond ticker, bond

**Estimated Rate** (Oprocentowanie szacunkowe):
A bond interest rate computed by the issue letter's rule (CPI of the right month plus margin, or the NBP reference rate for ROR/DOR) for a period the MF has not yet published, the input being already published. The MF-published rate always wins.
_Avoid_: forecast rate

**Forecast Rate** (Oprocentowanie prognozowane):
A bond interest rate for a period whose input (CPI or NBP reference rate) is not published yet, so the last known one stands in. Becomes an Estimated Rate once the input is published.
_Avoid_: Estimated Rate, guess

**Early Redemption** (Wcześniejszy wykup):
Selling a Bond Series back to the issuer before maturity: it names its Lot (ADR-0007) and pays the early-redemption fee, capped at the accrued interest.
_Avoid_: sale, early sell

**Net Value** (Wartość netto):
What redeeming one bond of a Bond Series' Lot today would pay, a Lot's being that times its bonds: the bond's gross value less the early-redemption fee (none at maturity) and the tax the Account's Tax Regime withholds on its profit. Shown in the Dochód stały tab; the Dashboard's after-tax toggle takes it.
_Avoid_: after-tax value, redemption value

**Draft** (Szkic):
A Transaction the app proposes for confirmation (a maturity redemption, a Rollover, a bond coupon, a Recurring Rule's occurrence or a Term Deposit's interest), computed from what is due and not yet recorded, never stored; confirming it saves an ordinary Transaction. A Term Deposit's maturity is a Draft too, confirmed by ending or renewing the deposit.
_Avoid_: pending transaction, suggestion

**Rollover** (Zamiana):
Buying a new Bond Series with proceeds of a maturing one at the MF exchange price (e.g. 99.90 PLN).
_Avoid_: swap, conversion

## Results

**History** (Historia):
The daily series of portfolio value by Asset Class, recomputed from Transactions and historical prices — never stored snapshots.
_Avoid_: snapshot (a Valuation Snapshot is a different thing), daily log

**Valuation Snapshot** (Migawka wyceny):
The value and Net Deposits of Total and of each Account as the Dashboard showed them after a Successful Refresh, kept at most once a calendar day (a later refresh that day replaces it). The Dashboard compares today's figures with the newest Valuation Snapshot of an earlier day, splitting the change into the market change and the Deposits and Withdrawals in between.
_Avoid_: History, checkpoint, last update

**Net Deposits** (Wpłaty netto):
Deposits minus Withdrawals up to a date, in PLN; a foreign-currency one at its own rate (the user's, else the NBP Rate D-1), not at the cost of the foreign cash it moves.

**XIRR**:
Money-weighted annual return of the portfolio or an Account, based on Deposits and Withdrawals.

**TWR**:
Time-weighted return, independent of the timing of Deposits and Withdrawals. Drawdown and benchmark comparison are based on it.

**Real Return** (Wynik realny):
The TWR over a period after the inflation of that period: (1 + TWR) / (1 + inflation) − 1, the inflation from the GUS month-on-month CPI spread evenly across each month's days.
_Avoid_: inflation-adjusted XIRR, real value

**Benchmark** (Benchmark):
CPI, a catalog Instrument or another Account into which every Deposit and Withdrawal of the View Scope is hypothetically invested on its date, without fees or taxes, optionally with "+x pp a year", to compare with the real portfolio.

**Sale Pair** (Para kupno–sprzedaż):
The units of one Lot one Sell closed, from the single FIFO engine: its cost, the revenue they brought, the days held and the Dividends attributed to them. The Sell Summary lists them with the statistics of the closed positions.
_Avoid_: trade, round trip

**Passive Income** (Dochód pasywny):
The net Dividends (DRIPs included) and interest received, with the bond coupons not entered yet as its forecast; a bond's interest paid at its redemption is not counted.

**Monthly Income Goal** (Miesięczny cel dochodu):
The Passive Income the user aims at each month, in PLN; each month shows its progress toward it.

**Investment Goal** (Cel inwestycyjny):
The value in PLN the user aims at for one View Scope, with an optional target date. Entered directly or worked out for FIRE from yearly expenses and a safe withdrawal rate (4% by default, i.e. 25 × the expenses). Total and each Account have their own; the Accounts' goals need not add up to the Total's.
_Avoid_: target, FIRE number, Allocation Target

**Reconciliation** (Uzgadnianie):
Pairing Transactions from two Origins (e.g. spreadsheet vs XTB import) and resolving their differences.
_Avoid_: diff, merge
