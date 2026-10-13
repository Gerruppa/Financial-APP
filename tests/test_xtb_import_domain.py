"""Reading XTB statements into entries and Transactions (L-17, spec 7)."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from financial_app.domain.currencies import NbpRate
from financial_app.domain.instruments import Instrument
from financial_app.domain.prices import BOSSA, YAHOO
from financial_app.domain.transactions import Origin, TransactionType
from financial_app.domain.xtb_import import (
    EntryContext,
    EntryKind,
    XtbError,
    XtbStatement,
    match_instrument,
    parse_statement,
    unresolved,
    warsaw_day,
    xtb_draft,
    xtb_entries,
    yahoo_symbol,
)
from xtb_rows import Row, op, sheet_rows

IKE = "54925231"
MAIN = "54864339"
USD = NbpRate("USD", Decimal("3.7000"), date(2026, 7, 29), "145/A/NBP/2026")


def statement(account: str, *operations: Row, product: str = "IKE") -> XtbStatement:
    return parse_statement(sheet_rows(account, operations, product))


def instrument(id: int, name: str, currency: str = "PLN", **symbols: str) -> Instrument:
    return Instrument(
        id=id,
        name=name,
        asset_class_id=1,
        asset_class_name="ETF",
        quote_currency=currency,
        source_symbols=symbols,
        fallback_order=(),
    )


def test_a_statement_names_its_account_and_lists_its_operations() -> None:
    read = statement(IKE, op("Free funds interest", datetime(2026, 9, 1, 11), 0.03, "11", "Free-funds Interest"))
    assert read.account == IKE
    assert read.until == datetime(2026, 10, 13, 8, 35, 51)
    assert [o.amount for o in read.operations] == [Decimal("0.03")]
    assert read.product == "IKE"


def test_another_sheet_is_not_a_statement() -> None:
    with pytest.raises(XtbError, match="Cash Operations"):
        parse_statement([("Konto", "Data"), ("IKE", datetime(2026, 1, 1))])


def test_the_polish_day_follows_summer_time() -> None:
    assert warsaw_day(datetime(2026, 10, 8, 21, 59)) == date(2026, 10, 8)
    assert warsaw_day(datetime(2026, 10, 8, 22, 1)) == date(2026, 10, 9)  # CEST, UTC+2
    assert warsaw_day(datetime(2026, 1, 8, 22, 59)) == date(2026, 1, 8)  # CET, UTC+1
    assert warsaw_day(datetime(2026, 1, 8, 23, 1)) == date(2026, 1, 9)


def test_an_order_filled_in_parts_is_one_buy() -> None:
    read = statement(
        IKE,
        op("Stock purchase", datetime(2026, 7, 30, 9, 52, 14), -6717.44, "1376673050",
           "OPEN BUY 15/15.3224 @ 118.580", "ISAC.UK", "MSCI ACWI", "2725934815"),
        op("Stock purchase", datetime(2026, 7, 30, 9, 52, 14), -144.38, "1376673049",
           "OPEN BUY 0.3224/15.3224 @ 118.580", "ISAC.UK", "MSCI ACWI", "2725934815"),
    )  # fmt: skip
    [entry] = xtb_entries([read])
    assert entry.kind is EntryKind.BUY
    assert (entry.quantity, entry.price, entry.amount) == (Decimal("15.3224"), Decimal("118.580"), Decimal("6861.82"))
    assert entry.external_id == "xtb-1376673049"
    assert entry.day == date(2026, 7, 30)


def test_a_sell_with_its_ticker_in_the_comment() -> None:
    read = statement(
        IKE,
        op("Stock sell", datetime(2026, 10, 12, 8, 1), 870.88, "2", "CLOSE BUY ETFPZUWORLD.PL 8/10 @ 108.86",
           "ETFPZUWORLD.PL", "MSCI World", "9"),
        op("Stock sell", datetime(2026, 10, 12, 8, 1), 217.72, "1", "CLOSE BUY ETFPZUWORLD.PL 2/10 @ 108.86",
           "ETFPZUWORLD.PL", "MSCI World", "9"),
        op("Stock purchase", datetime(2026, 10, 12, 8, 2), -1121.44, "3", "OPEN BUY XTB.PL 8 @ 140.18",
           "XTB.PL", "XTB", "10"),
    )  # fmt: skip
    sell, buy = xtb_entries([read])
    assert (sell.kind, sell.quantity, sell.amount) == (EntryKind.SELL, Decimal(10), Decimal("1088.60"))
    assert (buy.kind, buy.quantity, buy.price) == (EntryKind.BUY, Decimal(8), Decimal("140.18"))


def test_interest_carries_the_tax_withheld_that_month() -> None:
    read = statement(
        MAIN,
        op("Free funds interest", datetime(2026, 8, 4, 17, 46), 0.11, "21", "Free-funds Interest 2026-07"),
        op("Free funds interest tax", datetime(2026, 8, 4, 17, 26), -0.03, "20", "Free-funds Interest Tax 2026-07"),
        product="My Trades",
    )
    [entry] = xtb_entries([read])
    assert (entry.kind, entry.amount, entry.withholding_tax) == (EntryKind.INTEREST, Decimal("0.11"), Decimal("0.03"))
    draft = xtb_draft(entry, EntryContext(account_id=1))
    assert (draft.transaction_type, draft.actual_amount, draft.instrument_id) == (
        TransactionType.DIVIDEND,
        Decimal("0.08"),
        None,
    )


def test_a_transfer_between_two_imported_accounts_is_a_cash_transfer() -> None:
    main = statement(
        MAIN,
        op("IKE deposit", datetime(2026, 10, 8, 21, 14, 45), -1000.08, "1472819108",
           "Transfer out operation on account with id 54864339"),
        op("Deposit", datetime(2026, 10, 8, 21, 14, 15), 1000.0, "1472819061", "Adyen BLIK deposit"),
        product="My Trades",
    )  # fmt: skip
    ike = statement(
        IKE,
        op("IKE deposit", datetime(2026, 10, 8, 21, 14, 45), 1000.08, "1472779276",
           "Transfer in operation on account with id 54925231"),
    )  # fmt: skip
    deposit, transfer = xtb_entries([main, ike])
    assert (deposit.kind, deposit.account) == (EntryKind.DEPOSIT, MAIN)
    assert (transfer.kind, transfer.account, transfer.target) == (EntryKind.TRANSFER, MAIN, IKE)
    assert transfer.external_id == "xtb-1472819108+1472779276"
    draft = xtb_draft(transfer, EntryContext(account_id=1, target_account_id=2))
    assert (draft.transaction_type, draft.target_account_id, draft.actual_amount) == (
        TransactionType.CASH_TRANSFER,
        2,
        Decimal("1000.08"),
    )


def test_a_transfer_whose_leg_was_imported_alone_leaves_the_other_leg() -> None:
    main = statement(
        MAIN,
        op("IKE deposit", datetime(2026, 7, 24, 6, 45), -1000.0, "6", "Transfer out operation"),
        product="My Trades",
    )
    ike = statement(IKE, op("IKE deposit", datetime(2026, 7, 24, 6, 45), 1000.0, "5", "Transfer in operation"))
    [transfer] = xtb_entries([main, ike])
    assert unresolved(transfer, set()) == transfer
    assert unresolved(transfer, {"xtb-6+5"}) is None
    assert unresolved(transfer, {"xtb-6", "xtb-5"}) is None
    withdrawal = unresolved(transfer, {"xtb-5"})
    assert withdrawal is not None
    assert (withdrawal.kind, withdrawal.account, withdrawal.external_id) == (EntryKind.WITHDRAWAL, MAIN, "xtb-6")
    deposit = unresolved(transfer, {"xtb-6"})
    assert deposit is not None
    assert (deposit.kind, deposit.account, deposit.external_id) == (EntryKind.DEPOSIT, IKE, "xtb-5")


def test_a_transfer_leg_alone_is_a_deposit_or_withdrawal() -> None:
    ike = statement(
        IKE,
        op("IKE deposit", datetime(2026, 7, 24, 6, 45), 1000.0, "5", "Transfer in operation on account with id 1"),
    )
    main = statement(
        MAIN,
        op("IKE deposit", datetime(2026, 7, 24, 6, 45), -1000.0, "6", "Transfer out operation on account with id 2"),
    )
    [deposit] = xtb_entries([ike])
    [withdrawal] = xtb_entries([main])
    assert (deposit.kind, deposit.amount, deposit.note) == (EntryKind.DEPOSIT, Decimal(1000), "IKE deposit")
    assert withdrawal.kind is EntryKind.WITHDRAWAL


def test_an_unknown_operation_is_listed_as_unsupported() -> None:
    read = statement(IKE, op("Swap", datetime(2026, 7, 24, 6, 45), -1.5, "5", "SWAP"))
    [entry] = xtb_entries([read])
    assert entry.kind is EntryKind.UNSUPPORTED
    assert "Swap" in entry.note
    with pytest.raises(XtbError, match="nieobsługiwana"):
        xtb_draft(entry, EntryContext(account_id=1))


def test_a_foreign_buy_is_converted_by_xtb_at_the_accounts_fee() -> None:
    read = statement(
        IKE,
        op("Stock purchase", datetime(2026, 7, 30, 12, 19), -213.52, "7", "OPEN BUY 0.4754 @ 119.020",
           "ISAC.UK", "MSCI ACWI", "8"),
    )  # fmt: skip
    [entry] = xtb_entries([read])
    isac = instrument(4, "ISAC", "USD")
    draft = xtb_draft(entry, EntryContext(account_id=2, instrument=isac, nbp_rate=USD, fee_percent=Decimal("0.5")))
    assert draft.actual_amount == Decimal("213.52")
    assert draft.fx_conversion_fee_percent == Decimal("0.5")
    assert (draft.origin, draft.external_id) == (Origin.BROKER, "xtb-7")
    with pytest.raises(XtbError, match="Brak kursu NBP USD"):
        xtb_draft(entry, EntryContext(account_id=2, instrument=isac))


def test_a_pln_buy_takes_what_xtb_charged_above_the_value_as_commission() -> None:
    read = statement(
        IKE,
        op("Stock purchase", datetime(2026, 10, 9, 7), -975.0, "7", "OPEN BUY XTB.PL 7 @ 139.00", "XTB.PL", "XTB", "8"),
    )
    [entry] = xtb_entries([read])
    draft = xtb_draft(entry, EntryContext(account_id=2, instrument=instrument(5, "XTB")))
    assert (draft.commission, draft.actual_amount) == (Decimal("2.00"), Decimal("975.00"))


def test_an_xtb_ticker_matches_an_instrument_by_symbol_or_name() -> None:
    isac = instrument(1, "ISAC", "USD")
    sxr8 = instrument(2, "iShares Core S&P 500", "EUR", **{YAHOO: "SXR8.DE"})
    xtb = instrument(3, "XTB S.A.", **{BOSSA: "XTB"})
    catalog = [isac, sxr8, xtb]
    assert yahoo_symbol("ISAC.UK") == "ISAC.L"
    assert yahoo_symbol("AAPL.US") == "AAPL"
    assert match_instrument("ISAC.UK", catalog) == isac
    assert match_instrument("SXR8.DE", catalog) == sxr8
    assert match_instrument("XTB.PL", catalog) == xtb
    assert match_instrument("VWCE.DE", catalog) is None
