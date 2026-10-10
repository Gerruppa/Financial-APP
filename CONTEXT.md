# Personal Investment Tracker

A single-user, local application for tracking a personal investment portfolio: the user records every transaction by hand (or imports it), and the app values holdings, computes results and prepares tax data. It re-implements the inwestomat.eu "Portfolio tracker" Google Sheet (v2.0.1). UI is Polish; code is English — each term below gives the Polish UI label in parentheses.

## Accounts and instruments

**Account** (Konto):
A place where the user holds cash and positions, e.g. an IKE at a broker or a bank deposit. Has an Account Type, one or more Cash Currencies and an optional FX Conversion Fee.
_Avoid_: wallet, portfolio, platform, broker

**Account Type** (Typ konta):
The legal wrapper of an Account — Regular, IKE, IKZE, OIPE, PPK, OKI or Deposit — which determines its Tax Regime.
_Avoid_: account kind, wrapper

**Tax Regime** (Sposób opodatkowania):
The rules by which gains on an Account are taxed (e.g. 19% Belka per sale for Regular, exemption for IKE, not yet defined for OKI).
_Avoid_: tax mode, tax strategy

**Cash Currency** (Waluta rachunku):
A currency in which an Account can hold cash. An Account with only PLN converts every foreign-currency trade automatically.
_Avoid_: sub-account, currency account

**FX Conversion Fee** (Opłata za przewalutowanie):
A percentage a broker adds to the market rate when it converts currency for a foreign-currency trade on a PLN Account (e.g. 0.5% at XTB). Applied per Transaction only when the user marks it; recorded as a Cost of the transaction.
_Avoid_: spread, FX commission

**Instrument** (Instrument):
Anything that can be held and priced: a stock, ETF, fund, bond series, metal, crypto pair or a manually priced asset. Has one Asset Class, a quote currency, an optional ISIN and a Source Symbol per Price Source. Each listing is its own Instrument: the same ISIN on two exchanges or in two currencies gives two Instruments.
_Avoid_: ticker, security, asset, symbol

**Source Symbol** (Symbol w źródle):
The identifier of an Instrument in one Price Source (e.g. `PZU.WA` in Yahoo, `pzu` in Stooq).
_Avoid_: ticker

**Asset Class** (Klasa aktywów):
A user-editable category used for allocation, e.g. Akcje zagraniczne, Obligacje skarbowe polskie, Metale i surowce.
_Avoid_: category, asset type

**Multi-asset Split** (Podział Multi-asset):
The percentage breakdown of one Multi-asset Instrument across Asset Classes, summing to 100%.
_Avoid_: allocation, look-through

**View Scope** (Widok):
What a screen is computed for: **Total** (all Accounts) or a single Account. Accounts are the sub-portfolios; there is no grouping level between them and Total.
_Avoid_: sub-portfolio, portfolio group, filter

**Investment Strategy** (Strategia inwestycyjna):
The set of Allocation Targets, optionally refined by Instrument Targets inside each Asset Class. Total has one; each Account may optionally have its own.
_Avoid_: model portfolio, plan

**Allocation Target** (Cel %):
The desired share of an Asset Class in the whole portfolio, used for rebalancing.
_Avoid_: target weight

**Instrument Target** (Cel w klasie):
The desired share of an Instrument within its Asset Class; may name an Instrument not held yet.
_Avoid_: sub-target, weight

**Planned Deposit** (Planowana wpłata):
An amount the user intends to invest, split across Asset Classes and Instruments toward the Investment Strategy without selling anything.
_Avoid_: contribution, top-up

**Buyback Spread** (Spread odkupu):
The percentage below spot price at which a dealer buys back a physical metal Instrument. Its value is spot × the unit's metal weight (entered in grams) × (1 − Buyback Spread).
_Avoid_: discount, haircut

## Transactions and holdings

**Transaction** (Transakcja):
One user-recorded event on an Account: Deposit, Withdrawal, Buy, Sell, Dividend, Cost, Split, Currency Exchange, Cash Transfer, Security Transfer or DRIP.
_Avoid_: operation, trade, entry

**Dividend** (Dywidenda / odsetki):
A payout of an Instrument, or interest (with or without an Instrument), recorded with its gross amount and the withholding tax taken at source, both in its own currency. The net amount goes into PLN cash (converted) or foreign cash of the same currency.
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
The ordered list of Price Sources tried for an Asset Class. An Instrument uses only the sources it has a Source Symbol for, in that order; with none it has no automatic valuation.
_Avoid_: priority, source chain

**Stale Price** (Nieaktualna cena):
The last known Quote of an Instrument, still used for valuation, after the latest refresh failed for it in every Price Source.
_Avoid_: old price, cached price

**Distribution Policy** (Polityka dywidendowa):
Whether a fund pays out its income (Dystrybucja) or reinvests it (Akumulacja). Entered by the user, like the fund's TER and domicile.
_Avoid_: dividend type

## Bonds

**Bond Series** (Seria obligacji):
A Polish retail treasury bond issue identified by type, maturity month and year, e.g. `EDO0735`. It is an Instrument; each purchase of it is a separate Lot.
_Avoid_: bond ticker, bond

**Estimated Rate** (Oprocentowanie szacunkowe):
A bond interest rate computed from CPI plus margin for a period the MF has not yet published. The MF-published rate always wins.
_Avoid_: forecast rate

**Rollover** (Zamiana):
Buying a new Bond Series with proceeds of a maturing one at the MF exchange price (e.g. 99.90 PLN).
_Avoid_: swap, conversion

## Results

**History** (Historia):
The daily series of portfolio value by Asset Class, recomputed from Transactions and historical prices — never stored snapshots.
_Avoid_: snapshot, daily log

**Net Deposits** (Wpłaty netto):
Deposits minus Withdrawals up to a date.

**XIRR**:
Money-weighted annual return of the portfolio or an Account, based on Deposits and Withdrawals.

**TWR**:
Time-weighted return, independent of the timing of Deposits and Withdrawals. Drawdown and benchmark comparison are based on it.

**Benchmark** (Benchmark):
An Instrument or CPI into which every Deposit is hypothetically invested on its date, to compare with the real portfolio.

**Reconciliation** (Uzgadnianie):
Pairing Transactions from two Origins (e.g. spreadsheet vs XTB import) and resolving their differences.
_Avoid_: diff, merge
