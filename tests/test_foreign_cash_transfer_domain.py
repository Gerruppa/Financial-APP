"""A Cash Transfer in a foreign currency (issue #125): it moves the oldest foreign-cash Lots to the target Account with
their dates and costs, realising no FX result, and is worth its amount at the NBP Rate (D-1) in PLN."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.contribution_limits import contributions
from financial_app.domain.currencies import NbpRate
from financial_app.domain.lots import Lot, foreign_cash
from financial_app.domain.portfolio_history import daily_history
from financial_app.domain.save_warnings import CashShortfall, save_warnings
from financial_app.domain.transactions import (
    TransactionDraft,
    TransactionError,
    TransactionType,
    cash_balances,
    cash_transfer,
    currency_exchange,
    deposit_or_withdrawal,
)

REGULAR, IKZE = 1, 2


def _usd_rate(rate: str = "4.00") -> NbpRate:
    return NbpRate("USD", Decimal(rate), date(2026, 1, 9), "006/A/NBP/2026")


def _exchange(account: int, foreign: str, pln: str, *, day: int) -> TransactionDraft:
    return currency_exchange(account, date(2026, 1, day), "USD", Decimal(foreign), Decimal(pln))


def _transfer(amount: str, *, day: int = 10, source: int = REGULAR, target: int = IKZE) -> TransactionDraft:
    return cash_transfer(source, date(2026, 1, day), target, Decimal(amount), cash_currency="USD", nbp_rate=_usd_rate())


def _cash(transactions: list[TransactionDraft]) -> dict[int, tuple[tuple[Lot, ...], Decimal]]:
    return {usd.account_id: (usd.lots, usd.realized_result) for usd in foreign_cash(transactions)}


def test_transfer_moves_the_oldest_usd_lots_with_their_dates_and_costs() -> None:
    exchanges = [_exchange(REGULAR, "100", "360", day=1), _exchange(REGULAR, "100", "380", day=2)]
    transfer = _transfer("150")

    assert transfer.actual_amount == Decimal("600.00")  # 150 USD at the NBP Rate of 4.00
    assert transfer.tax_amount == Decimal("600.00")
    assert transfer.cash_change == 0
    assert cash_balances([*exchanges, transfer], currency="USD") == {REGULAR: Decimal(50), IKZE: Decimal(150)}
    cash = _cash([*exchanges, transfer])
    assert cash[REGULAR] == ((Lot(date(2026, 1, 2), Decimal(50), Decimal(190), Decimal(190)),), Decimal(0))
    assert cash[IKZE] == (
        (
            Lot(date(2026, 1, 1), Decimal(100), Decimal(360), Decimal(360)),
            Lot(date(2026, 1, 2), Decimal(50), Decimal(190), Decimal(190)),
        ),
        Decimal(0),
    )


def test_moved_lots_take_their_place_by_date_on_the_target() -> None:
    transactions = [
        _exchange(REGULAR, "100", "360", day=1),
        _exchange(IKZE, "100", "400", day=5),
        _transfer("100"),
    ]

    [first, second] = _cash(transactions)[IKZE][0]
    assert (first.date, second.date) == (date(2026, 1, 1), date(2026, 1, 5))


def test_a_shortfall_arrives_at_the_nbp_value_and_leaves_a_negative_lot_behind() -> None:
    transactions = [_exchange(REGULAR, "100", "360", day=1), _transfer("150")]

    cash = _cash(transactions)
    assert cash[REGULAR] == ((Lot(date(2026, 1, 10), Decimal(-50), Decimal(-200), Decimal(-200)),), Decimal(0))
    assert cash[IKZE][0] == (
        Lot(date(2026, 1, 1), Decimal(100), Decimal(360), Decimal(360)),
        Lot(date(2026, 1, 10), Decimal(50), Decimal(200), Decimal(200)),
    )


def test_moved_lots_close_a_negative_lot_on_the_target_like_incoming_cash() -> None:
    # IKZE spent 100 USD it did not hold, at 4.20 zł a dollar
    overspent = currency_exchange(IKZE, date(2026, 1, 3), "USD", Decimal(100), Decimal(420), to_pln=True)
    transactions = [_exchange(REGULAR, "100", "360", day=1), overspent, _transfer("100")]

    lots, realized = _cash(transactions)[IKZE]
    assert lots == ()
    assert realized == Decimal(60)  # dollars that cost 360 zł went for 420 zł


def test_a_usd_transfer_into_an_ikze_counts_towards_its_limit_at_the_nbp_value() -> None:
    accounts = [
        Account("XTB", "XTB", AccountType.REGULAR, ("PLN", "USD"), id=REGULAR),
        Account("IKZE", "XTB", AccountType.IKZE, ("PLN", "USD"), id=IKZE),
    ]

    assert contributions([_transfer("150")], accounts, 2026)[AccountType.IKZE] == Decimal("600.00")


def test_deleting_a_usd_transfer_whose_dollars_the_target_spent_warns_of_its_usd_balance() -> None:
    accounts = [
        Account("XTB", "XTB", AccountType.REGULAR, ("PLN", "USD"), id=REGULAR),
        Account("IKZE", "XTB", AccountType.IKZE, ("PLN", "USD"), id=IKZE),
    ]
    exchange = _exchange(REGULAR, "100", "360", day=1).with_id(1)
    transfer = _transfer("100").with_id(2)
    spent = currency_exchange(IKZE, date(2026, 1, 12), "USD", Decimal(100), Decimal(400), to_pln=True).with_id(3)

    warnings = save_warnings([exchange, transfer, spent], [exchange, spent], accounts, [], [], {})

    assert CashShortfall("IKZE", "USD", Decimal(-100)) in warnings.negative_cash


def test_a_usd_transfer_moves_its_nbp_value_in_net_deposits_and_its_dollars_in_history() -> None:
    transactions = [
        deposit_or_withdrawal(REGULAR, date(2026, 1, 1), TransactionType.DEPOSIT, Decimal(360)),
        _exchange(REGULAR, "100", "360", day=1),
        _transfer("100"),
    ]

    # History values the dollars at 4.10, unlike the transfer's own NBP Rate (D-1) of 4.00
    history_rates = {"USD": [_usd_rate("4.10")]}
    before, after = daily_history(transactions, {}, {}, history_rates, date(2026, 1, 9), date(2026, 1, 10))

    assert before.accounts == {REGULAR: Decimal("410.00")}  # 0 zł and 100 USD at 4.10
    assert before.account_net_deposits == {REGULAR: Decimal(360)}
    assert after.accounts == {REGULAR: Decimal(0), IKZE: Decimal("410.00")}
    # 100 USD at the transfer's NBP Rate of 4.00 leaves REGULAR and reaches IKZE
    assert after.account_net_deposits == {REGULAR: Decimal(-40), IKZE: Decimal(400)}
    assert before.net_deposits == after.net_deposits == Decimal(360)


def test_a_foreign_transfer_is_worth_its_amount_at_the_nbp_rate() -> None:
    with pytest.raises(TransactionError, match="Brak kursu NBP USD"):
        cash_transfer(REGULAR, date(2026, 1, 10), IKZE, Decimal(100), cash_currency="USD")
    with pytest.raises(TransactionError, match="z dokładnością do setnych"):
        _transfer("100.001")
