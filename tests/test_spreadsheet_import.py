"""Importing the Transakcje sheet (spec 7, issue #20), on a synthetic workbook with no real data."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.currencies import MissingNbpRateError, NbpRate
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.spreadsheet_import import (
    COLUMNS,
    SheetError,
    SheetLine,
    Ticker,
    TickerKind,
    classify_ticker,
    fingerprints,
    parse_lines,
    sheet_draft,
)
from financial_app.domain.transactions import Origin, TransactionType, buy_or_sell
from financial_app.persistence.accounts import add_account, list_accounts
from financial_app.persistence.db import init_db
from financial_app.persistence.instruments import add_instrument, list_asset_classes, list_instruments
from financial_app.persistence.transactions import add_transaction, list_transactions
from financial_app.sources.spreadsheet import Decisions, preview_import, read_sheet_lines, save_import

HEADER = list(COLUMNS.values())
USD = NbpRate("USD", Decimal("3.6500"), date(2026, 4, 23), "086/A/NBP/2026")
EUR = NbpRate("EUR", Decimal("4.2500"), date(2026, 4, 21), "077/A/NBP/2026")


class FakeRates:
    """Answers NBP Rates from a fixed table, and counts the lookups."""

    def __init__(self, table: dict[str, NbpRate]) -> None:
        self.table = table
        self.lookups: list[tuple[str, date]] = []

    def before(self, currency: str, day: date) -> NbpRate:
        self.lookups.append((currency, day))
        if currency not in self.table:
            raise MissingNbpRateError(f"Brak kursu NBP {currency}. Zapis zablokowany.")
        return self.table[currency]


def row(**values: object) -> list[object]:
    """One sheet row, by the sheet's column names; unset cells are empty."""
    defaults: dict[str, object] = {
        "Konto": "IKE",
        "Data": datetime(2026, 4, 24),
        "Ticker": "LON:ISAC",
        "Waluta": "USD",
        "Nazwa": "iShares MSCI ACWI",
        "Klasa aktywów": "Akcje zagraniczne",
        "Rodzaj transakcji": "Zakup",
        "Liczba": 0.3479,
        "Cena": 114.72,
        "Prowizje": 0.0,
        "Kurs PLN transakcji": 3.6503,
        "Cena nominalna": 1.0,
        "Total PLN": 145.68,
        "Komentarz": "IKE MSCI ACWI",
    }
    defaults.update(values)
    return [defaults[label] for label in HEADER]


def lines_of(*rows: list[object]) -> list[SheetLine]:
    return parse_lines(HEADER, rows)


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
def ike(engine: Engine) -> int:
    return add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN", "USD"))).id


def test_tickers_of_the_sheet_formats_are_recognised() -> None:
    assert classify_ticker("Gotówka").kind is TickerKind.CASH
    assert classify_ticker("Waluty_USD").kind is TickerKind.FOREIGN_CASH
    assert classify_ticker("Waluty_USD").name == "USD"
    assert classify_ticker("EDO-040836") == Ticker(TickerKind.BOND, "EDO0836")
    assert classify_ticker("EDO-040836").name == "EDO0836"
    assert classify_ticker("FRA:SXR8").kind is TickerKind.INSTRUMENT
    assert classify_ticker("FRA:SXR8").name == "SXR8"
    assert classify_ticker("WSE:PKO") == Ticker(TickerKind.INSTRUMENT, "PKO")
    assert classify_ticker("PKO") == Ticker(TickerKind.INSTRUMENT, "PKO")  # Biznesradar: a bare code


def test_a_sheet_without_a_needed_column_is_refused() -> None:
    header = [label for label in HEADER if label != "Total PLN"]
    with pytest.raises(SheetError, match="Total PLN"):
        parse_lines(header, [])


def test_blank_rows_are_skipped_and_numbers_read_exactly() -> None:
    lines = parse_lines(HEADER, [row(), [None] * len(HEADER)])
    assert len(lines) == 1
    assert lines[0].quantity == Decimal("0.3479")
    assert lines[0].price == Decimal("114.72")
    assert lines[0].day == date(2026, 4, 24)


def test_identical_rows_get_distinct_fingerprints_and_stay_stable() -> None:
    twice = lines_of(row(), row())
    ids = fingerprints(twice)
    assert ids[0] != ids[1]
    assert fingerprints(lines_of(row(), row())) == ids
    assert fingerprints(lines_of(row(Konto="IKZE")))[0] != ids[0]


def test_a_foreign_buy_takes_the_app_amount_from_the_sheet_rate_and_the_nbp_rate(ike: int) -> None:
    line = lines_of(row())[0]
    draft = sheet_draft(line, account_id=ike, instrument_id=7, nbp_rate=USD, external_id="sheet-x")
    assert draft.transaction_type is TransactionType.BUY
    # Calculated as for any Buy: 0,3479 × 114,72 × 3,6503, not the sheet's rounded Total PLN of 145,68
    assert draft.actual_amount == Decimal("145.69")
    assert draft.fx_rate == Decimal("3.6503")
    assert draft.nbp_rate == USD
    assert draft.origin is Origin.SPREADSHEET
    assert draft.external_id == "sheet-x"


def test_a_pln_deposit_and_a_foreign_currency_exchange_become_their_transactions(ike: int) -> None:
    deposit = lines_of(
        row(Ticker="Gotówka", Waluta="PLN", **{"Rodzaj transakcji": "Wpłata środków"}, **{"Total PLN": 500.0})
    )[0]
    draft = sheet_draft(deposit, account_id=ike, instrument_id=None, nbp_rate=None, external_id="d")
    assert draft.transaction_type is TransactionType.DEPOSIT
    assert draft.actual_amount == Decimal("500.0")

    exchange = lines_of(row(Ticker="Waluty_USD", Liczba=100.0, **{"Total PLN": 365.0}))[0]
    draft = sheet_draft(exchange, account_id=ike, instrument_id=None, nbp_rate=None, external_id="e")
    assert draft.transaction_type is TransactionType.CURRENCY_EXCHANGE
    assert draft.cash_currency == "USD"
    assert draft.quantity == Decimal("100.0")


def test_an_unknown_kind_is_refused_with_its_name(ike: int) -> None:
    line = lines_of(row(**{"Rodzaj transakcji": "Dywidenda"}))[0]
    with pytest.raises(SheetError, match="Dywidenda"):
        sheet_draft(line, account_id=ike, instrument_id=1, nbp_rate=USD, external_id="x")


def test_preview_lists_what_is_unmatched_and_saves_nothing(engine: Engine, ike: int) -> None:
    lines = lines_of(
        row(),
        row(Konto="Metale Fizyczne", Ticker="COMEX:GCW00", Waluta="PLN", Liczba=1.0, Cena=10.0, **{"Total PLN": 10.0}),
    )
    preview = preview_import(engine, lines, FakeRates({"USD": USD}), Decisions())
    assert preview.unmatched_accounts == ["Metale Fizyczne"]
    assert preview.unmatched_instruments == ["GCW00", "ISAC"]
    assert preview.new_instruments["ISAC"].asset_class == "Akcje zagraniczne"
    assert [item.status for item in preview.lines] == ["ok", "error"]
    assert list_transactions(engine) == []


def test_save_creates_the_instruments_and_imports_every_row_once(engine: Engine, ike: int) -> None:
    lines = lines_of(
        row(),
        row(
            **{
                "Rodzaj transakcji": "Wpłata środków",
                "Ticker": "Gotówka",
                "Waluta": "PLN",
                "Total PLN": 500.0,
                "Nazwa": "Gotówka",
                "Klasa aktywów": "Gotówka",
            }
        ),
    )
    rates = FakeRates({"USD": USD})
    decisions = Decisions(accounts={"IKE": ike})

    saved = save_import(engine, lines, rates, decisions)

    assert saved.to_save == 2
    transactions = list_transactions(engine)
    assert sorted(t.transaction_type for t in transactions) == [TransactionType.BUY, TransactionType.DEPOSIT]
    assert {t.origin for t in transactions} == {Origin.SPREADSHEET}
    instruments = {instrument.name: instrument for instrument in list_instruments(engine)}
    assert instruments["ISAC"].quote_currency == "USD"
    classes = {asset_class.id: asset_class.name for asset_class in list_asset_classes(engine)}
    assert classes[instruments["ISAC"].asset_class_id] == "Akcje zagraniczne"

    again = preview_import(engine, lines, rates, decisions)
    assert [item.status for item in again.lines] == ["duplicate", "duplicate"]
    assert save_import(engine, lines, rates, decisions).duplicates == 2
    assert len(list_transactions(engine)) == 2


def test_a_row_without_an_account_blocks_the_whole_save(engine: Engine, ike: int) -> None:
    lines = lines_of(
        row(),
        row(
            Konto="OBLIGACJE",
            **{"Rodzaj transakcji": "Wpłata środków", "Ticker": "Gotówka", "Waluta": "PLN", "Total PLN": 500.0},
        ),
    )
    with pytest.raises(SheetError, match="Wiersz 3"):
        save_import(engine, lines, FakeRates({"USD": USD}), Decisions(accounts={"IKE": ike}))
    assert list_transactions(engine) == []
    assert [instrument.name for instrument in list_instruments(engine)] == []


def test_a_missing_nbp_rate_blocks_that_row_with_the_reason(engine: Engine, ike: int) -> None:
    lines = lines_of(row(Waluta="JPY"))
    preview = preview_import(engine, lines, FakeRates({}), Decisions(accounts={"IKE": ike}))
    assert preview.lines[0].status == "error"
    assert "JPY" in preview.lines[0].message


def test_a_chosen_existing_instrument_is_used_instead_of_a_new_one(engine: Engine, ike: int) -> None:
    from financial_app.domain.instruments import InstrumentDraft
    from financial_app.persistence.instruments import add_instrument

    existing = add_instrument(
        engine, InstrumentDraft("iShares MSCI ACWI", list_asset_classes(engine)[0].id, "USD", market="LSE")
    )
    lines = lines_of(row(Ticker="LON:ISAC"))
    preview = preview_import(
        engine, lines, FakeRates({"USD": USD}), Decisions(accounts={"IKE": ike}, instruments={"ISAC": existing.id})
    )
    assert preview.lines[0].status == "ok"
    assert preview.lines[0].draft is not None
    assert preview.lines[0].draft.instrument_id == existing.id
    assert preview.new_instruments == {}


def test_read_sheet_lines_reads_the_transakcje_tab_of_a_workbook(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Transakcje"
    sheet.append(HEADER)
    sheet.append(row())
    workbook.save(path)

    lines = read_sheet_lines(path)

    assert len(lines) == 1
    assert lines[0].ticker == "LON:ISAC"
    assert lines[0].day == date(2026, 4, 24)


def test_a_workbook_without_the_transakcje_tab_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "other.xlsx"
    openpyxl.Workbook().save(path)
    with pytest.raises(SheetError, match="Transakcje"):
        read_sheet_lines(path)


def test_accounts_and_asset_classes_are_the_saved_ones(engine: Engine, ike: int) -> None:
    assert [account.name for account in list_accounts(engine)] == ["IKE"]
    assert any(asset_class.name == "Akcje zagraniczne" for asset_class in list_asset_classes(engine))


def test_a_row_like_a_manual_transaction_is_held_back_until_the_user_keeps_it(engine: Engine, ike: int) -> None:
    instrument = add_instrument(engine, InstrumentDraft("ISAC", list_asset_classes(engine)[0].id, "USD"))
    rates = FakeRates({"USD": USD})
    lines = lines_of(row())
    by_hand = buy_or_sell(
        ike,
        date(2026, 4, 24),
        TransactionType.BUY,
        instrument.id,
        Decimal("0.3479"),
        Decimal("114.72"),
        fx_rate=Decimal("3.6503"),
        nbp_rate=USD,
    )
    add_transaction(engine, by_hand)
    decisions = Decisions(accounts={"IKE": ike}, instruments={"ISAC": instrument.id})

    held = preview_import(engine, lines, rates, decisions)
    assert [item.status for item in held.lines] == ["similar"]
    assert held.to_save == 0
    assert save_import(engine, lines, rates, decisions).to_save == 0
    assert len(list_transactions(engine)) == 1

    keep = Decisions(
        accounts={"IKE": ike},
        instruments={"ISAC": instrument.id},
        keep_similar=frozenset({held.lines[0].external_id}),
    )
    assert save_import(engine, lines, rates, keep).to_save == 1
    assert len(list_transactions(engine)) == 2


def test_an_existing_bond_without_a_manual_price_gets_the_sheet_price_and_keeps_one_it_has(
    engine: Engine, ike: int
) -> None:
    class_id = list_asset_classes(engine)[0].id
    plain = add_instrument(engine, InstrumentDraft("EDO0836", class_id, "PLN"))
    priced = add_instrument(engine, InstrumentDraft("EDO0636", class_id, "PLN", manual_price=Decimal("101.5")))
    bond_row = dict(Konto="IKE", Ticker="EDO-040836", Waluta="PLN", Liczba=50.0, Cena=100.0, **{"Total PLN": 5000.0})
    other_row = dict(bond_row, Ticker="EDO-170636")
    lines = lines_of(row(**bond_row), row(**other_row))

    save_import(engine, lines, FakeRates({}), Decisions(accounts={"IKE": ike}))

    by_name = {instrument.name: instrument for instrument in list_instruments(engine)}
    assert by_name["EDO0836"].manual_price == Decimal("100")
    assert by_name["EDO0636"].manual_price == Decimal("101.5")
    assert plain.id == by_name["EDO0836"].id and priced.id == by_name["EDO0636"].id


def test_editing_the_total_or_comment_of_a_row_keeps_its_fingerprint() -> None:
    original = fingerprints(lines_of(row()))
    edited = fingerprints(lines_of(row(**{"Total PLN": 150.0, "Komentarz": "poprawiony"})))
    assert original == edited
