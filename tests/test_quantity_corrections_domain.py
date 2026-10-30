"""Quantity corrections (#278): a Sell or Security Transfer needing a few more units than its Account held is offered
a correcting Transaction, a Buy of the missing units or the Sell trimmed to what was held; nothing is tolerated in
the FIFO engine itself."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.currencies import NbpRate
from financial_app.domain.lots import open_positions, realized_results
from financial_app.domain.quantity_corrections import CORRECTION_COMMENT, Fix, quantity_shortfalls
from financial_app.domain.transactions import (
    Origin,
    TransactionDraft,
    TransactionError,
    TransactionType,
    buy_or_sell,
    security_transfer,
)

ACCOUNT, WALLET, COIN = 1, 2, 7
DAY = date(2026, 3, 2)
NBSP = "\xa0"


def _buy(quantity: str, price: str = "100", day: date = date(2026, 1, 5)) -> TransactionDraft:
    return buy_or_sell(ACCOUNT, day, TransactionType.BUY, COIN, Decimal(quantity), Decimal(price))


def _sell(quantity: str, price: str = "110", day: date = DAY) -> TransactionDraft:
    return buy_or_sell(ACCOUNT, day, TransactionType.SELL, COIN, Decimal(quantity), Decimal(price))


def test_a_covered_history_has_no_shortfall() -> None:
    assert quantity_shortfalls([_buy("2"), _sell("2")]) == []


def test_a_small_gap_is_offered_a_buy_at_cost_zero_by_default() -> None:
    sold = _sell("2.001")
    [shortfall] = quantity_shortfalls([_buy("2"), sold])
    assert shortfall.uncovered is sold
    assert (shortfall.held, shortfall.gap, shortfall.held_cost) == (Decimal(2), Decimal("0.001"), Decimal(200))
    assert not shortfall.large and shortfall.fix is Fix.FREE_BUY
    assert shortfall.fixes == (Fix.FREE_BUY, Fix.PRICED_BUY, Fix.TRIM)
    # The units missing are worth what the Sell got for them: 0.001 x 110 zł
    assert shortfall.value == Decimal("0.11")

    added, replacement = shortfall.correction(Fix.FREE_BUY)
    assert replacement is None and added is not None
    assert (added.account_id, added.date, added.transaction_type, added.instrument_id) == (
        ACCOUNT,
        DAY,
        TransactionType.BUY,
        COIN,
    )
    assert (added.quantity, added.actual_amount, added.comment) == (Decimal("0.001"), Decimal(0), CORRECTION_COMMENT)
    assert realized_results([_buy("2"), sold, added]) == {ACCOUNT: Decimal("20.11")}


def test_the_buy_at_the_day_price_costs_what_the_sell_got_for_the_units() -> None:
    sold = _sell("2.001")
    [shortfall] = quantity_shortfalls([_buy("2"), sold])
    added, replacement = shortfall.correction(Fix.PRICED_BUY)
    assert replacement is None and added is not None
    assert (added.quantity, added.price, added.actual_amount) == (Decimal("0.001"), Decimal(110), Decimal("0.11"))
    assert realized_results([_buy("2"), sold, added]) == {ACCOUNT: Decimal("20.00")}


def test_trimming_keeps_the_sell_amount_at_a_higher_price() -> None:
    sold = _sell("2.001")
    [shortfall] = quantity_shortfalls([_buy("2"), sold])
    added, trimmed = shortfall.correction(Fix.TRIM)
    assert added is None and trimmed is not None
    assert (trimmed.quantity, trimmed.actual_amount) == (Decimal(2), sold.actual_amount)
    assert trimmed.price == Decimal("110.055")
    assert realized_results([_buy("2"), trimmed]) == {ACCOUNT: Decimal("20.11")}


def test_each_fix_says_what_it_changes() -> None:
    [shortfall] = quantity_shortfalls([_buy("2"), _sell("2.001")])
    assert f"wynik ze sprzedaży: 20,11{NBSP}zł" in shortfall.effect(Fix.FREE_BUY)
    assert f"wynik ze sprzedaży: 20,00{NBSP}zł" in shortfall.effect(Fix.PRICED_BUY)
    assert "2 szt. zamiast 2,001 szt." in shortfall.effect(Fix.TRIM)


def test_a_gap_above_one_percent_preselects_nothing() -> None:
    [shortfall] = quantity_shortfalls([_buy("2"), _sell("2.1")])
    assert shortfall.large and shortfall.fix is None
    [chosen] = quantity_shortfalls([_buy("2"), _sell("2.1")], {shortfall.key: Fix.TRIM})
    assert chosen.fix is Fix.TRIM


def test_nothing_held_cannot_be_trimmed() -> None:
    [shortfall] = quantity_shortfalls([_sell("1")])
    assert shortfall.held == 0 and shortfall.fixes == (Fix.FREE_BUY, Fix.PRICED_BUY)


def test_later_shortfalls_follow_the_fix_of_an_earlier_one() -> None:
    """A trimmed transfer brings the wallet fewer units than one topped up, so its later Sell lacks more."""
    moved = security_transfer(ACCOUNT, DAY, WALLET, COIN, Decimal("2.001"))
    sold = buy_or_sell(WALLET, date(2026, 4, 1), TransactionType.SELL, COIN, Decimal("2.0015"), Decimal(120))
    history = [_buy("2"), moved, sold]

    first, second = quantity_shortfalls(history)
    assert (first.uncovered, first.fixes, first.value) == (moved, (Fix.FREE_BUY, Fix.TRIM), Decimal("0.10"))
    assert (second.uncovered, second.gap) == (sold, Decimal("0.0005"))

    trimmed, again = quantity_shortfalls(history, {first.key: Fix.TRIM})
    assert again.gap == Decimal("0.0015")
    _, replacement = trimmed.correction(Fix.TRIM)
    assert replacement is not None and replacement.quantity == Decimal(2)


def test_an_imported_sell_gets_an_imported_correction() -> None:
    imported = replace(_sell("2.001"), origin=Origin.BROKER, external_id="okx-10")
    [shortfall] = quantity_shortfalls([_buy("2"), imported])
    assert shortfall.key == "okx-10"
    added, _ = shortfall.correction(Fix.FREE_BUY)
    assert added is not None and (added.origin, added.external_id) == (Origin.BROKER, "okx-10-correction")


def test_a_buy_at_cost_zero_opens_a_lot_costing_nothing() -> None:
    bought = buy_or_sell(ACCOUNT, date(2026, 1, 5), TransactionType.BUY, COIN, Decimal(2), Decimal(100))
    free = buy_or_sell(ACCOUNT, DAY, TransactionType.BUY, COIN, Decimal("0.001"), Decimal(0))
    assert (free.actual_amount, free.tax_amount, free.cash_change) == (Decimal(0), Decimal(0), Decimal(0))

    sold = buy_or_sell(ACCOUNT, DAY, TransactionType.SELL, COIN, Decimal("2.001"), Decimal(110))
    [position] = open_positions([bought, free])
    assert (position.quantity, position.cost) == (Decimal("2.001"), Decimal(200))
    assert open_positions([bought, free, sold]) == []
    assert realized_results([bought, free, sold]) == {ACCOUNT: Decimal("20.11")}


def test_a_foreign_buy_at_cost_zero_needs_no_nbp_rate() -> None:
    free = buy_or_sell(ACCOUNT, DAY, TransactionType.BUY, COIN, Decimal("0.001"), Decimal(0))
    assert free.nbp_rate is None
    rate = NbpRate("USD", Decimal(4), date(2026, 2, 27), "40/A/NBP/2026")
    priced = buy_or_sell(ACCOUNT, DAY, TransactionType.BUY, COIN, Decimal("0.001"), Decimal(0), nbp_rate=rate)
    assert (priced.actual_amount, priced.tax_amount) == (Decimal(0), Decimal(0))


def test_only_a_buy_without_commission_may_cost_nothing() -> None:
    with pytest.raises(TransactionError, match="Cena"):
        buy_or_sell(ACCOUNT, DAY, TransactionType.SELL, COIN, Decimal(1), Decimal(0))
    with pytest.raises(TransactionError, match="prowizji"):
        buy_or_sell(ACCOUNT, DAY, TransactionType.BUY, COIN, Decimal(1), Decimal(0), Decimal(1))
    with pytest.raises(TransactionError, match="Kwota"):
        TransactionDraft(
            ACCOUNT, DAY, TransactionType.BUY, Decimal(0), instrument_id=COIN, quantity=Decimal(1), price=Decimal(5)
        )
