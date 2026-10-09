"""Parity of the Portfolio with the Portfolio tab of the user's Inwestomat copy (spec 7, 9; ADR-0004; issue #21).

The sheet's Transakcje rows are imported as they are, with the sheet's own FX rates, and the app's Portfolio is compared
with the sheet's Portfolio tab: quantities, costs, values, results and cash balances, within 0.01 PLN. Prices and FX
rates are frozen at the export date (the sheet's "Obecna Cena" and "Obecny kurs waluty"), so nothing needs the network.

The workbook is personal data: it stays in ``reference/`` (git-ignored), is read at test time, and the tests are skipped
when it is missing. Nothing from it is copied here. A difference is accepted only when the sheet's own rows explain it:
its size must equal the amount the reason in ``DEVIATIONS`` predicts, so a difference that merely looks similar fails.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import MissingNbpRateError, NbpRate
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.lots import Position, open_positions
from financial_app.domain.spreadsheet_import import SheetLine, classify_ticker, fingerprints
from financial_app.domain.transactions import PLN, TransactionType, cash_balances
from financial_app.persistence.accounts import add_account, list_accounts
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import list_instruments, update_instrument
from financial_app.persistence.transactions import list_transactions
from financial_app.sources.spreadsheet import Decisions, read_sheet_lines, save_import

REFERENCE = Path(__file__).resolve().parents[1] / "reference" / "Newest portfolio.xlsx"
TOLERANCE = Decimal("0.01")
CASH = "Gotówka"

BROKER_PLN = (
    "Arkusz liczy koszt z Total PLN (PLN faktycznie przelany przez brokera przy przewalutowaniu), aplikacja z ilości × "
    "ceny × kursu transakcji i prowizji w PLN (decyzja z #20, 6dfd147). Różnica idzie w koszt, zysk i saldo gotówki."
)
BOND_PRICES = (
    "Jedna Serie obligacji ma jedną Manual Price (spec 3.4), a arkusz wycenia każdy zakup osobno. Różnica to suma "
    "ilości × różnic cen zakupów względem Manual Price."
)
# Known differences, keyed by (Konto, Instrument name or CASH): the measures they may cover, and the reason
DEVIATIONS: dict[tuple[str, str], tuple[frozenset[str], str]] = {
    ("IKE", "ISAC"): (frozenset({"koszt", "zysk"}), BROKER_PLN),
    ("IKE", "VUAA"): (frozenset({"koszt", "zysk"}), BROKER_PLN),
    ("IKE", CASH): (frozenset({"saldo"}), BROKER_PLN),
    ("IKZE", "SXR8"): (frozenset({"koszt", "zysk"}), BROKER_PLN),
    ("IKZE", "VWCE"): (frozenset({"koszt", "zysk"}), BROKER_PLN),
    ("IKZE", CASH): (frozenset({"saldo"}), BROKER_PLN),
    ("Metale Fizyczne", "GCW00"): (frozenset({"koszt", "zysk"}), BROKER_PLN),
    ("OBLIGACJE", "EDO0636"): (frozenset({"wartość", "zysk"}), BOND_PRICES),
}


@dataclass(frozen=True)
class SheetRow:
    """A Position of the sheet's Portfolio tab, or a Konto's cash (``key`` = CASH). Rows of one Bond Series are summed.

    ``purchases`` keeps each sheet row's (quantity, price), to tell how far the sheet's own prices differ from the one
    Manual Price the app uses.
    """

    account: str
    key: str
    currency: str
    quantity: Decimal
    cost: Decimal
    price: Decimal | None
    rate: Decimal | None
    value: Decimal
    result: Decimal
    purchases: tuple[tuple[Decimal, Decimal], ...]


@dataclass(frozen=True)
class Difference:
    key: tuple[str, str]
    measure: str
    expected: Decimal | None
    actual: Decimal | None


@dataclass(frozen=True)
class AppView:
    """What the app says about the Portfolio, keyed by (Konto, Instrument name or CASH)."""

    positions: dict[tuple[str, str], Position]
    cash: dict[str, Decimal]
    prices: dict[str, Decimal | None]  # Manual Price per Instrument name
    rates: dict[str, Decimal]


class FrozenRates:
    """NBP Rates frozen at the sheet's own rates: the rate of each row, and the latest rate per currency."""

    def __init__(self, table: dict[tuple[str, date], NbpRate], latest: dict[str, NbpRate]) -> None:
        self.table = table
        self._latest = latest

    def before(self, currency: str, day: date) -> NbpRate:
        if (currency, day) not in self.table:
            raise MissingNbpRateError(f"Brak kursu NBP {currency} dla {day}.")
        return self.table[(currency, day)]

    def latest(self, currency: str) -> NbpRate:
        if currency not in self._latest:
            raise MissingNbpRateError(f"Brak kursu NBP {currency}.")
        return self._latest[currency]


def _decimal(value: object) -> Decimal | None:
    return None if value is None or value == "" else Decimal(str(value))


def read_portfolio_tab(path: Path) -> list[SheetRow]:
    """The Portfolio tab's rows, one per Position and Konto, read by the names of its columns."""
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = workbook["Portfolio"].iter_rows(values_only=True)
        header = [str(cell or "").strip() for cell in next(rows)]
        column = {name: index for index, name in enumerate(header) if name}
        grouped: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
        for row in rows:
            values: dict[str, object] = {
                name: row[index] if index < len(row) else None for name, index in column.items()
            }
            account = str(values["Konto"] or "").strip()
            if not account:
                continue
            ticker = str(values["Ticker"] or "").strip()
            grouped[(account, classify_ticker(ticker).name if ticker else CASH)].append(values)
    finally:
        workbook.close()

    result = []
    for (account, key), members in grouped.items():

        def total(name: str, members: list[Mapping[str, object]] = members) -> Decimal:
            return sum((_decimal(member[name]) or Decimal(0) for member in members), Decimal(0))

        last = members[-1]
        result.append(
            SheetRow(
                account=account,
                key=key,
                currency=str(last["Waluta"] or PLN).strip(),
                quantity=total("Liczba"),
                cost=total("Koszt PLN"),
                price=_decimal(last["Obecna Cena"]),
                rate=_decimal(last["Obecny kurs waluty"]),
                value=total("Obecna Wartość PLN"),
                result=total("Zysk / Strata PLN"),
                purchases=tuple(
                    (_decimal(member["Liczba"]) or Decimal(0), _decimal(member["Obecna Cena"]) or Decimal(0))
                    for member in members
                    if key != CASH
                ),
            )
        )
    return result


@pytest.fixture(scope="module")
def sheet_lines() -> list[SheetLine]:
    if not REFERENCE.exists():
        pytest.skip("Brak arkusza referencyjnego w reference/ – test porównawczy pominięty.")
    return read_sheet_lines(REFERENCE)


@pytest.fixture(scope="module")
def sheet_portfolio() -> list[SheetRow]:
    return read_portfolio_tab(REFERENCE)


@pytest.fixture(scope="module")
def imported(
    tmp_path_factory: pytest.TempPathFactory, sheet_lines: list[SheetLine], sheet_portfolio: list[SheetRow]
) -> Engine:
    """The sheet's Transakcje saved into a fresh database, with the Portfolio's frozen prices on the Instruments."""
    table = {
        (line.currency, line.day): NbpRate(line.currency, line.rate, line.day - timedelta(days=1), "arkusz")
        for line in sheet_lines
    }
    latest = {
        row.currency: NbpRate(row.currency, row.rate, date(2026, 10, 8), "arkusz")
        for row in sheet_portfolio
        if row.rate
    }
    engine = init_db(tmp_path_factory.mktemp("parity") / "parity.sqlite3")
    currencies: dict[str, set[str]] = defaultdict(lambda: {PLN})
    for line in sheet_lines:
        currencies[line.account].add(line.currency)
    for account, codes in currencies.items():
        wrapper = {"IKE": AccountType.IKE, "IKZE": AccountType.IKZE}.get(account, AccountType.REGULAR)
        add_account(engine, AccountDraft(account, "Arkusz", wrapper, tuple(sorted(codes))))
    save_import(engine, sheet_lines, FrozenRates(table, latest), Decisions())

    prices = {row.key: row.price for row in sheet_portfolio if row.price is not None}
    for instrument in list_instruments(engine):
        if instrument.name in prices:
            update_instrument(
                engine,
                instrument.id,
                InstrumentDraft(
                    instrument.name,
                    instrument.asset_class_id,
                    instrument.quote_currency,
                    instrument.market,
                    prices[instrument.name],
                ),
            )
    return engine


def app_view(engine: Engine, sheet_portfolio: list[SheetRow]) -> AppView:
    transactions = list_transactions(engine)
    accounts = {account.id: account.name for account in list_accounts(engine)}
    instruments = list_instruments(engine)
    names = {instrument.id: instrument.name for instrument in instruments}
    positions = {(accounts[p.account_id], names[p.instrument_id]): p for p in open_positions(reversed(transactions))}
    cash = {accounts[account_id]: amount for account_id, amount in cash_balances(transactions).items()}
    prices = {instrument.name: instrument.manual_price for instrument in instruments}
    rates = {row.currency: row.rate for row in sheet_portfolio if row.rate}
    return AppView(positions, cash, prices, rates)


def _pln(amount: Decimal | None, currency: str, rates: dict[str, Decimal]) -> Decimal | None:
    """An amount in ``currency`` in PLN at the sheet's latest rate, or None when it cannot be known."""
    if amount is None:
        return None
    if currency == PLN:
        return amount
    return amount * rates[currency] if currency in rates else None


def compare(app: AppView, sheet_portfolio: list[SheetRow]) -> list[Difference]:
    """Every measure of the sheet's Portfolio tab that differs from the app's by more than TOLERANCE."""
    differences: list[Difference] = []

    def check(key: tuple[str, str], measure: str, expected: Decimal, actual: Decimal | None) -> None:
        if actual is None or abs(expected - actual) > TOLERANCE:
            differences.append(Difference(key, measure, expected, actual))

    listed = set()
    for row in sheet_portfolio:
        key = (row.account, row.key)
        listed.add(key)
        if row.key == CASH:
            check(key, "saldo", row.value, app.cash.get(row.account, Decimal(0)))
            continue
        position = app.positions.get(key)
        if position is None:
            differences.append(Difference(key, "pozycja", row.quantity, None))
            continue
        price = _pln(app.prices.get(row.key), row.currency, app.rates)
        check(key, "liczba", row.quantity, position.quantity)
        check(key, "koszt", row.cost, position.cost)
        check(key, "wartość", row.value, None if price is None else position.value(price))
        check(key, "zysk", row.result, None if price is None else position.result(price))
    for key, position in app.positions.items():
        if key not in listed:
            differences.append(Difference(key, "pozycja w aplikacji", None, position.quantity))
    return differences


def broker_gaps(lines: list[SheetLine], engine: Engine) -> tuple[dict[tuple[str, str], Decimal], dict[str, Decimal]]:
    """Per Position, the cost the sheet's Total PLN adds over the app's Actual Amounts; per Konto, the cash it adds."""
    saved = {t.external_id: t for t in list_transactions(engine)}
    cost_gap: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    cash_gap: dict[str, Decimal] = defaultdict(Decimal)
    for line, external_id in zip(lines, fingerprints(lines), strict=True):
        transaction = saved.get(external_id)
        if transaction is None or not transaction.transaction_type.is_buy_or_sell:
            continue
        gap = line.total - transaction.actual_amount
        if transaction.transaction_type is TransactionType.BUY:
            cost_gap[(line.account, classify_ticker(line.ticker).name)] += gap
            cash_gap[line.account] -= gap
        else:
            cash_gap[line.account] += gap
    return cost_gap, cash_gap


def _value_gap(row: SheetRow, app: AppView) -> Decimal:
    """The sheet's own purchase prices against the Manual Price, for the quantity each purchase row holds."""
    price = app.prices.get(row.key)
    if price is None or row.currency != PLN:
        return Decimal(0)
    return sum((quantity * (sheet_price - price) for quantity, sheet_price in row.purchases), Decimal(0))


def predicted(
    difference: Difference,
    lines: list[SheetLine],
    engine: Engine,
    sheet_portfolio: list[SheetRow],
    app: AppView,
) -> Decimal:
    """The sheet minus the app, as the deviation's reason predicts it. The result moves by the value gap less the cost
    gap, since the result is the value less the cost."""
    cost_gap, cash_gap = broker_gaps(lines, engine)
    if difference.measure == "saldo":
        return cash_gap.get(difference.key[0], Decimal(0))
    if difference.measure == "koszt":
        return cost_gap.get(difference.key, Decimal(0))
    rows = {(row.account, row.key): row for row in sheet_portfolio}
    value_gap = _value_gap(rows[difference.key], app)
    if difference.measure == "wartość":
        return value_gap
    return value_gap - cost_gap.get(difference.key, Decimal(0))


def unexplained(
    differences: list[Difference],
    lines: list[SheetLine],
    engine: Engine,
    sheet_portfolio: list[SheetRow],
    app: AppView,
) -> list[str]:
    """The differences the deviations do not account for: those outside DEVIATIONS, and those whose size the sheet's
    own rows do not predict."""
    found = []
    for difference in differences:
        label = f"{difference.key} {difference.measure}: arkusz {difference.expected}, aplikacja {difference.actual}"
        if difference.key not in DEVIATIONS or difference.measure not in DEVIATIONS[difference.key][0]:
            found.append(label)
            continue
        if difference.expected is None or difference.actual is None:
            found.append(label)
            continue
        size = predicted(difference, lines, engine, sheet_portfolio, app)
        if abs((difference.expected - difference.actual) - size) > TOLERANCE:
            found.append(f"{label} – wyjaśnienie daje {size}")
    return found


def test_portfolio_matches_the_sheet_within_a_grosz(
    imported: Engine, sheet_lines: list[SheetLine], sheet_portfolio: list[SheetRow]
) -> None:
    app = app_view(imported, sheet_portfolio)
    found = unexplained(compare(app, sheet_portfolio), sheet_lines, imported, sheet_portfolio, app)
    assert not found, "\n".join(found)


def test_every_known_deviation_still_occurs(imported: Engine, sheet_portfolio: list[SheetRow]) -> None:
    """A deviation that no longer differs is stale and must be removed from DEVIATIONS."""
    app = app_view(imported, sheet_portfolio)
    keys = {difference.key for difference in compare(app, sheet_portfolio)}
    stale = [key for key in DEVIATIONS if key not in keys]
    assert not stale, f"Usuń nieaktualne odstępstwa: {stale}"
