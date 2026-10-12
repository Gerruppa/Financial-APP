"""Multi-asset Splits: one fixed split of an Instrument's value across Asset Classes (issue #75, spec 3.2 and 6.1)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.dashboard import dashboard
from financial_app.domain.instruments import Instrument, InstrumentDraft, InstrumentError
from financial_app.domain.lots import open_positions
from financial_app.domain.multi_asset import multi_asset_holdings
from financial_app.domain.portfolio_history import CASH_CLASS, HistoryPrice, daily_history
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell

IKE, XTB = 1, 2
VANGUARD, PZU = 10, 20
MULTI, STOCKS, BONDS = 12, 3, 5
NAMES = {MULTI: "Multi-asset", STOCKS: "Akcje zagraniczne", BONDS: "Obligacje skarbowe zagraniczne"}
SPLIT = {STOCKS: Decimal(80), BONDS: Decimal(20)}


def _instrument(instrument_id: int, class_id: int, split: dict[int, Decimal] | None = None) -> Instrument:
    return Instrument(
        "X",
        class_id,
        "PLN",
        multi_asset_split=split or {},
        id=instrument_id,
        asset_class_name=NAMES[class_id],
        fallback_order=(),
        in_multi_asset_class=class_id == MULTI,
        split_class_names={i: NAMES[i] for i in split or {}},
    )


INSTRUMENTS = {VANGUARD: _instrument(VANGUARD, MULTI, SPLIT), PZU: _instrument(PZU, STOCKS)}


def _deposit(amount: str, account: int = IKE) -> TransactionDraft:
    return TransactionDraft(account, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(amount))


def _buy(quantity: str, price: str, instrument: int = VANGUARD, account: int = IKE) -> TransactionDraft:
    return buy_or_sell(account, date(2026, 1, 2), TransactionType.BUY, instrument, Decimal(quantity), Decimal(price))


def test_a_split_must_sum_to_100_percent() -> None:
    with pytest.raises(InstrumentError, match="100%.*teraz 90,00 %"):
        InstrumentDraft("V80A", MULTI, "EUR", multi_asset_split={STOCKS: Decimal(70), BONDS: Decimal(20)})


def test_each_share_of_a_split_lies_between_0_and_100_percent() -> None:
    with pytest.raises(InstrumentError, match="od 0 do 100%"):
        InstrumentDraft("V80A", MULTI, "EUR", multi_asset_split={STOCKS: Decimal(120), BONDS: Decimal(-20)})


def test_a_zero_share_is_left_out_and_no_split_is_allowed() -> None:
    draft = InstrumentDraft("V80A", MULTI, "EUR", multi_asset_split={STOCKS: Decimal(100), BONDS: Decimal(0)})

    assert draft.multi_asset_split == {STOCKS: Decimal(100)}
    assert InstrumentDraft("V80A", MULTI, "EUR").multi_asset_split == {}


def test_a_value_is_split_across_the_classes_and_the_parts_add_up_exactly() -> None:
    thirds = {STOCKS: Decimal("33.33"), BONDS: Decimal("66.67")}
    instrument = _instrument(VANGUARD, MULTI, thirds)

    parts = instrument.class_parts(Decimal("100.01"))

    assert dict(parts) == {NAMES[STOCKS]: Decimal("33.333333"), NAMES[BONDS]: Decimal("66.676667")}
    assert sum(value for _, value in parts) == Decimal("100.01")


def test_an_instrument_without_a_split_counts_whole_in_its_own_class() -> None:
    assert _instrument(PZU, STOCKS).class_parts(Decimal(50)) == [(NAMES[STOCKS], Decimal(50))]
    assert _instrument(VANGUARD, MULTI).class_parts(Decimal(50)) == [(NAMES[MULTI], Decimal(50))]


def test_an_instrument_is_multi_asset_by_its_class_or_its_split() -> None:
    renamed = replace(_instrument(VANGUARD, MULTI), asset_class_name="Fundusze mieszane")

    assert _instrument(VANGUARD, MULTI).is_multi_asset
    assert renamed.is_multi_asset
    assert _instrument(VANGUARD, STOCKS, SPLIT).is_multi_asset
    assert not _instrument(PZU, STOCKS).is_multi_asset


def test_history_values_a_split_instrument_in_each_class_of_its_split() -> None:
    history = daily_history(
        [_deposit("1000"), _buy("10", "50")],
        INSTRUMENTS,
        {VANGUARD: [HistoryPrice(date(2026, 1, 2), Decimal(60), "PLN")]},
        {},
        date(2026, 1, 2),
        date(2026, 1, 2),
    )

    assert history[0].classes == {
        CASH_CLASS: Decimal(500),
        NAMES[STOCKS]: Decimal(480),
        NAMES[BONDS]: Decimal(120),
    }
    assert history[0].account_classes[IKE][NAMES[BONDS]] == Decimal(120)
    assert history[0].total == Decimal(1100)


def test_the_dashboard_allocation_includes_the_splits() -> None:
    accounts = [Account("IKE", "", AccountType.REGULAR, ("PLN",), id=IKE)]
    transactions = [_deposit("1000"), _buy("10", "50"), _buy("1", "100", instrument=PZU)]

    board = dashboard(transactions, accounts, INSTRUMENTS, {VANGUARD: Decimal(60), PZU: Decimal(100)}, {}, None)

    assert {share.asset_class: share.value for share in board.classes} == {
        NAMES[STOCKS]: Decimal(580),
        CASH_CLASS: Decimal(400),
        NAMES[BONDS]: Decimal(120),
    }


def test_holdings_list_the_multi_asset_instruments_held_with_their_value_per_class() -> None:
    unsplit = _instrument(30, MULTI)
    instruments = {**INSTRUMENTS, 30: unsplit}
    transactions = [
        _deposit("2000"),
        _buy("10", "50"),
        _buy("1", "100", instrument=PZU),
        _buy("5", "20", instrument=30, account=XTB),
    ]

    holdings = multi_asset_holdings(open_positions(transactions), instruments, {VANGUARD: Decimal(60)}, None)

    assert [(h.instrument.id, h.value) for h in holdings] == [(VANGUARD, Decimal(600)), (30, Decimal(100))]
    assert dict(holdings[0].parts) == {NAMES[STOCKS]: Decimal(480), NAMES[BONDS]: Decimal(120)}
    assert holdings[1].priced is False
    assert holdings[1].parts == ((NAMES[MULTI], Decimal(100)),)


def test_holdings_follow_the_view_scope() -> None:
    transactions = [_deposit("2000"), _buy("10", "50"), _buy("2", "50", account=XTB)]

    holdings = multi_asset_holdings(open_positions(transactions), INSTRUMENTS, {VANGUARD: Decimal(60)}, XTB)

    assert [(h.instrument.id, h.value) for h in holdings] == [(VANGUARD, Decimal(120))]
