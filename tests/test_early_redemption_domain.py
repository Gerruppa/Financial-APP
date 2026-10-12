"""Early Redemption (L-5, spec 3.4.1, ADR-0007): a Sell of a Bond Series names the Lot it redeems, the FIFO engine
takes the units from that Lot alone, and the Sell carries the tax withheld at redemption; the dialog prefills it with
the gross value of one bond, the early-redemption fee and the tax."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.accounts import BELKA_RATE
from financial_app.domain.bond_redemption import EarlyRedemption, early_redemption
from financial_app.domain.bond_valuation import BondPrice, Cpi
from financial_app.domain.bonds import BondSeries, SeriesTerms, sale_month
from financial_app.domain.currencies import NbpRate
from financial_app.domain.lots import (
    InsufficientQuantityError,
    Lot,
    LotNotHeldError,
    open_lots,
    open_positions,
    realized_results,
    replay,
)
from financial_app.domain.profit_sources import profit_sources
from financial_app.domain.transactions import (
    Transaction,
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    security_transfer,
)

BONDS, IKE = 1, 2
EDO = 10


def _buy(transaction_id: int, day: date, quantity: int = 10, price: str = "100") -> Transaction:
    draft = buy_or_sell(BONDS, day, TransactionType.BUY, EDO, Decimal(quantity), Decimal(price))
    return draft.with_id(transaction_id)


def _redeem(
    day: date,
    quantity: int,
    lot_id: int | None,
    *,
    price: str = "105",
    fee: str = "0",
    tax: str = "0",
    account: int = BONDS,
) -> TransactionDraft:
    return buy_or_sell(
        account,
        day,
        TransactionType.SELL,
        EDO,
        Decimal(quantity),
        Decimal(price),
        Decimal(fee),
        withholding_tax=Decimal(tax),
        lot_id=lot_id,
    )


def test_a_redemption_takes_its_units_from_the_lot_it_names() -> None:
    first, second = _buy(1, date(2024, 5, 22)), _buy(2, date(2025, 3, 3), price="99.9")

    [position] = open_positions([first, second, _redeem(date(2025, 10, 8), 4, lot_id=2)])

    assert [(lot.date, lot.quantity, lot.opened_by) for lot in position.lots] == [
        (date(2024, 5, 22), Decimal(10), 1),
        (date(2025, 3, 3), Decimal(6), 2),
    ]
    assert position.lots[1].cost == Decimal("599.4")


def test_the_realised_result_counts_the_named_lots_cost() -> None:
    first, second = _buy(1, date(2024, 5, 22)), _buy(2, date(2025, 3, 3), price="99.9")
    redemption = _redeem(date(2025, 10, 8), 10, lot_id=2, price="103", fee="20", tax="3")

    # 10 × 103 less the 20 zł fee and the 3 zł tax, against the second Lot's 999 zł; the tax is no cost
    assert redemption.actual_amount == Decimal("1007")
    assert redemption.tax_amount == Decimal("1010")
    assert realized_results([first, second, redemption]) == {BONDS: Decimal("8")}


def test_a_redemption_without_a_lot_falls_back_to_fifo() -> None:
    first, second = _buy(1, date(2024, 5, 22)), _buy(2, date(2025, 3, 3))

    [position] = open_positions([first, second, _redeem(date(2025, 10, 8), 10, lot_id=None)])

    assert [lot.opened_by for lot in position.lots] == [2]


def test_a_lot_keeps_its_name_through_a_security_transfer() -> None:
    bought = _buy(1, date(2024, 5, 22))
    moved = security_transfer(BONDS, date(2025, 1, 2), IKE, EDO, Decimal(10)).with_id(2)

    [position] = open_positions([bought, moved, _redeem(date(2025, 10, 8), 3, lot_id=1, account=IKE)])

    assert (position.account_id, position.quantity, position.lots[0].opened_by) == (IKE, Decimal(7), 1)


def test_redeeming_more_than_the_named_lot_holds_is_blocked() -> None:
    first, second = _buy(1, date(2024, 5, 22)), _buy(2, date(2025, 3, 3), quantity=5)

    with pytest.raises(InsufficientQuantityError) as raised:
        open_positions([first, second, _redeem(date(2025, 10, 8), 6, lot_id=2)])

    assert (raised.value.held, raised.value.requested) == (Decimal(5), Decimal(6))


def test_a_lot_no_longer_held_cannot_be_redeemed() -> None:
    bought = _buy(1, date(2024, 5, 22))
    redemptions = [_redeem(date(2025, 10, 8), 10, lot_id=1), _redeem(date(2025, 11, 8), 1, lot_id=1)]

    with pytest.raises(LotNotHeldError, match="08.11.2025"):
        open_positions([bought, *redemptions])
    with pytest.raises(LotNotHeldError):
        open_positions([_redeem(date(2025, 10, 8), 1, lot_id=7), bought])


def test_open_lots_lists_the_lots_held_on_a_day_without_the_edited_redemption() -> None:
    first, second = _buy(1, date(2024, 5, 22)), _buy(2, date(2025, 3, 3))
    edited = _redeem(date(2025, 10, 8), 10, lot_id=1).with_id(3)
    later = _redeem(date(2026, 1, 5), 4, lot_id=2).with_id(4)
    transactions = [first, second, edited, later]

    lots = open_lots(transactions, BONDS, EDO, date(2025, 10, 8), edited_id=3)

    assert [(lot.opened_by, lot.quantity) for lot in lots] == [(1, Decimal(10)), (2, Decimal(10))]
    same_day = [first, _buy(5, date(2024, 5, 22), quantity=3)]
    assert [lot.opened_by for lot in open_lots(same_day, BONDS, EDO, date(2025, 1, 1))] == [1, 5]
    assert open_lots(transactions, BONDS, EDO, date(2024, 1, 1)) == ()
    assert open_lots(transactions, IKE, EDO, date(2025, 10, 8)) == ()


def test_only_a_sell_names_a_lot_or_has_tax_withheld() -> None:
    with pytest.raises(TransactionError, match="partii"):
        buy_or_sell(BONDS, date(2025, 1, 2), TransactionType.BUY, EDO, Decimal(1), Decimal(100), lot_id=1)
    with pytest.raises(TransactionError, match="podatku"):
        buy_or_sell(
            BONDS, date(2025, 1, 2), TransactionType.BUY, EDO, Decimal(1), Decimal(100), withholding_tax=Decimal(1)
        )
    usd = NbpRate("USD", Decimal("4"), date(2025, 1, 1), "001/A/NBP/2025")
    with pytest.raises(TransactionError, match="PLN"):
        buy_or_sell(
            BONDS,
            date(2025, 1, 2),
            TransactionType.SELL,
            EDO,
            Decimal(1),
            Decimal(100),
            withholding_tax=Decimal(1),
            nbp_rate=usd,
        )


def test_the_fee_and_tax_cannot_take_the_whole_redemption() -> None:
    with pytest.raises(TransactionError, match="Prowizja i podatek"):
        _redeem(date(2025, 10, 8), 1, lot_id=1, price="100", fee="60", tax="40")
    with pytest.raises(TransactionError, match="grosza"):
        _redeem(date(2025, 10, 8), 1, lot_id=1, tax="0.001")
    with pytest.raises(TransactionError, match="ujemny"):
        _redeem(date(2025, 10, 8), 1, lot_id=1, tax="-1")


def test_the_withheld_tax_counts_under_taxes_in_the_profit_sources() -> None:
    bought = _buy(1, date(2024, 5, 22), quantity=1)
    redemption = _redeem(date(2025, 10, 8), 1, lot_id=1, price="108.67", fee="2", tax="1.27")
    realized = realized_results([bought, redemption])[BONDS]

    sources = profit_sources([bought, redemption], [BONDS], realized, Decimal(0))

    assert realized == Decimal("5.40")
    assert (sources.price, sources.costs, sources.taxes) == (Decimal("8.67"), Decimal("-2"), Decimal("-1.27"))


def _series(name: str, *rates: str) -> BondSeries:
    sold = sale_month(name)
    padded = tuple(Decimal(rate) for rate in rates) + (None,) * (10 - len(rates))
    terms = SeriesTerms(name, "PL0", sold, sold, Decimal(100), Decimal("99.9"), Decimal("0.02"), padded, (None,))
    return BondSeries(EDO, name, terms)


def test_the_redemption_is_prefilled_per_bond_times_the_bonds_redeemed() -> None:
    # One bond: 108.67 zł gross, the 2 zł fee of a pre-September 2024 issue, 1.27 zł Belka (as in the net value)
    price = BondPrice(_series("EDO0534", "0.065", "0.0535"), date(2025, 10, 8), Cpi(()))
    lot = Lot(date(2024, 5, 22), Decimal(10), Decimal(1000), Decimal(1000), opened_by=1)

    redemption = early_redemption(price, lot, Decimal(4), BELKA_RATE)

    assert redemption == EarlyRedemption(Decimal("108.67"), Decimal("8.00"), Decimal("5.08"), Decimal(4))
    assert redemption is not None and redemption.net == Decimal("421.60")


def test_no_prefill_while_the_series_has_no_value() -> None:
    series = replace(_series("EDO0534", "0.065"), mf=None)
    price = BondPrice(series, date(2025, 10, 8), Cpi(()))
    lot = Lot(date(2024, 5, 22), Decimal(10), Decimal(1000), Decimal(1000))

    assert early_redemption(price, lot, Decimal(1), BELKA_RATE) is None


def test_replay_keeps_the_named_lots_for_every_caller() -> None:
    first, second = _buy(1, date(2024, 5, 22)), _buy(2, date(2025, 3, 3))

    result = replay([first, second, _redeem(date(2025, 10, 8), 10, lot_id=2, price="104")])

    assert [lot.opened_by for lot in result.positions[0].lots] == [1]
    assert result.realized == {BONDS: Decimal(40)}
