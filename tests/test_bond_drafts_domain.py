"""Maturity and Rollover as Drafts (L-6, spec 3.4.1): each Lot of a Bond Series still held on or after its maturity is a
Draft, confirmed as its redemption or as a Rollover into a new Series."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.bond_drafts import ROLLOVER_TYPES, MaturityDraft, maturity_drafts
from financial_app.domain.bond_valuation import BondData
from financial_app.domain.bonds import BondSeries, BondType, SeriesTerms
from financial_app.domain.instruments import Instrument
from financial_app.domain.lots import Lot, Position
from financial_app.domain.transactions import TransactionError, TransactionType

TODAY = date(2026, 10, 8)
BONDS = Account("Obligacje", "PKO BP", AccountType.BONDS, ("PLN",), id=1)
IKE = Account("IKE obligacje", "PKO BP", AccountType.IKE, ("PLN",), id=2)


def _instrument(instrument_id: int, name: str) -> Instrument:
    return Instrument(
        name, 1, "PLN", id=instrument_id, asset_class_name="Obligacje skarbowe polskie", fallback_order=()
    )


def _terms(name: str) -> SeriesTerms:
    sold = (date(2016, 6, 1), date(2016, 6, 30))
    return SeriesTerms(name, "PL0", *sold, Decimal(100), Decimal("99.9"), Decimal("0.01"), (Decimal("0.03"),) * 10, ())


EDO0626 = _instrument(10, "EDO0626")
EDO1035 = _instrument(11, "EDO1035")
ROS1026 = _instrument(12, "ROS1026")
INSTRUMENTS = {i.id: i for i in (EDO0626, EDO1035, ROS1026)}
DATA = BondData({10: BondSeries(10, "EDO0626", _terms("EDO0626"))})


def _lot(day: date, quantity: int, opened_by: int) -> Lot:
    return Lot(day, Decimal(quantity), Decimal(100 * quantity), Decimal(100 * quantity), opened_by=opened_by)


def _drafts(positions: list[Position], account_id: int | None = None) -> list[MaturityDraft]:
    return maturity_drafts(positions, INSTRUMENTS, [BONDS, IKE], DATA, TODAY, account_id)


def test_a_lot_held_past_its_maturity_is_a_draft_redeemed_at_its_maturity_value() -> None:
    position = Position(1, 10, (_lot(date(2016, 6, 15), 10, opened_by=7),))

    [draft] = _drafts([position])

    assert draft.account == BONDS
    assert draft.instrument == EDO0626
    assert draft.maturity == date(2026, 6, 15)
    assert draft.redemption is not None
    # Ten years at 3% compounded: 134.39 zł a bond, no fee at maturity, Belka on the 34.39 zł of interest
    assert draft.redemption.price == Decimal("134.39")
    assert draft.redemption.fee == Decimal(0)
    assert draft.redemption.tax == Decimal("65.30")
    assert draft.redemption.net == Decimal("1278.60")


def test_confirming_the_redemption_sells_the_lot_on_its_maturity_day() -> None:
    [draft] = _drafts([Position(1, 10, (_lot(date(2016, 6, 15), 10, opened_by=7),))])

    sell = draft.redemption_transaction()

    assert sell.transaction_type is TransactionType.SELL
    assert (sell.account_id, sell.instrument_id, sell.lot_id) == (1, 10, 7)
    assert sell.date == date(2026, 6, 15)
    assert sell.quantity == Decimal(10)
    assert sell.price == Decimal("134.39")
    assert sell.withholding_tax == Decimal("65.30")
    assert sell.actual_amount == Decimal("1278.60")


def test_a_rollover_buys_the_new_series_on_the_maturity_day_at_its_rollover_price() -> None:
    [draft] = _drafts([Position(1, 10, (_lot(date(2016, 6, 15), 10, opened_by=7),))])

    assert draft.rollover_series(BondType.EDO) == "EDO0636"
    assert draft.rollover_series(BondType.COI) == "COI0630"
    buy = draft.rollover_purchase(20, Decimal(10), Decimal("99.90"))

    assert buy.transaction_type is TransactionType.BUY
    assert (buy.account_id, buy.instrument_id, buy.date) == (1, 20, date(2026, 6, 15))
    assert buy.actual_amount == Decimal("999.00")
    assert "EDO0626" in buy.comment


def test_a_rollover_exchanges_no_more_bonds_than_the_lot_redeems() -> None:
    [draft] = _drafts([Position(1, 10, (_lot(date(2016, 6, 15), 10, opened_by=7),))])

    with pytest.raises(TransactionError, match="najwyżej 10"):
        draft.rollover_purchase(20, Decimal(11), Decimal("99.90"))


def test_lots_not_matured_yet_are_no_drafts_and_each_matured_lot_is_its_own() -> None:
    position = Position(1, 10, (_lot(date(2016, 6, 15), 10, opened_by=7), _lot(date(2016, 6, 20), 5, opened_by=8)))
    young = Position(1, 11, (_lot(date(2025, 10, 8), 10, opened_by=9),))

    drafts = _drafts([young, position])

    assert [draft.lot.opened_by for draft in drafts] == [7, 8]


def test_no_tax_is_withheld_on_an_ike_and_drafts_follow_the_view_scope() -> None:
    lot = _lot(date(2016, 6, 15), 10, opened_by=7)
    positions = [Position(1, 10, (lot,)), Position(2, 10, (lot,))]

    [ike] = _drafts(positions, account_id=2)

    assert ike.account == IKE
    assert ike.redemption is not None and ike.redemption.tax == Decimal(0)
    assert len(_drafts(positions)) == 2


def test_a_series_not_valued_is_a_draft_without_a_redemption_and_offers_no_family_rollover() -> None:
    [draft] = _drafts([Position(1, 12, (_lot(date(2020, 10, 1), 3, opened_by=4),))])

    assert draft.redemption is None
    assert draft.bond_type is BondType.ROS
    assert BondType.ROS not in ROLLOVER_TYPES
    assert BondType.EDO in ROLLOVER_TYPES
