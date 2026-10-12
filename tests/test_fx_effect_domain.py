"""The FX part of a foreign-currency Position's result (issue #89, spec 5): the FIFO Lots remember what they cost in
the Instrument's currency, so the result splits into a price effect and an FX effect."""

from datetime import date
from decimal import Decimal

from financial_app.domain.currencies import NbpRate
from financial_app.domain.lots import open_positions, realized_fx_results
from financial_app.domain.transactions import (
    BrokerConversion,
    SplitRatio,
    TransactionDraft,
    TransactionType,
    buy_or_sell,
    drip,
    security_transfer,
    split,
)

XTB, IKE, AAPL, PZU = 1, 2, 7, 8
USD_4 = NbpRate("USD", Decimal(4), date(2026, 1, 1), "1/A/NBP/2026")
USD_5 = NbpRate("USD", Decimal(5), date(2026, 2, 1), "2/A/NBP/2026")


def _trade(
    kind: TransactionType, quantity: str, price: str, rate: NbpRate, *, fee: str = "0", month: int = 1
) -> TransactionDraft:
    return buy_or_sell(
        XTB, date(2026, month, 2), kind, AAPL, Decimal(quantity), Decimal(price), Decimal(fee), nbp_rate=rate
    )


def test_a_foreign_position_splits_its_result_into_price_and_fx() -> None:
    # 10 × 100 USD at 4 zł with a 5 zł commission; today 120 USD at 5 zł
    [position] = open_positions([_trade(TransactionType.BUY, "10", "100", USD_4, fee="5")])

    assert position.cost == Decimal(4005)
    assert position.fx_result(Decimal(5)) == Decimal(1000)  # the 1000 USD paid, now worth 1 zł more each


def test_a_pln_position_has_no_fx_result() -> None:
    buy = buy_or_sell(XTB, date(2026, 1, 2), TransactionType.BUY, PZU, Decimal(10), Decimal(40), Decimal(5))

    [position] = open_positions([buy])

    assert position.fx_result(Decimal(1)) == Decimal(0)


def test_the_fx_result_leaves_out_the_brokers_conversion_fee() -> None:
    # The broker charged 4020 zł for 1000 USD worth 4000 zł at the market rate: the 20 zł fee is a cost, not FX
    buy = buy_or_sell(
        XTB,
        date(2026, 1, 2),
        TransactionType.BUY,
        AAPL,
        Decimal(10),
        Decimal(100),
        nbp_rate=USD_4,
        conversion=BrokerConversion(Decimal(4020), Decimal("0.5")),
    )

    [position] = open_positions([buy])

    assert position.fx_result(Decimal(4)) == Decimal(0)


def test_a_partial_sell_keeps_the_fx_basis_of_what_is_left_and_realises_the_rest() -> None:
    transactions = [
        _trade(TransactionType.BUY, "10", "100", USD_4),
        _trade(TransactionType.SELL, "4", "100", USD_5, month=2),
    ]

    [position] = open_positions(transactions)

    assert position.fx_result(Decimal(5)) == Decimal(600)  # 600 USD left, 1 zł more each
    assert realized_fx_results(transactions) == {XTB: Decimal(400)}  # 400 USD sold at 5 zł instead of 4


def test_a_split_and_a_security_transfer_keep_the_fx_basis() -> None:
    transactions = [
        _trade(TransactionType.BUY, "10", "100", USD_4),
        split(XTB, date(2026, 1, 5), AAPL, SplitRatio(2, 1)),
        security_transfer(XTB, date(2026, 1, 6), IKE, AAPL, Decimal(20)),
    ]

    [position] = open_positions(transactions)

    assert position.account_id == IKE
    assert position.fx_result(Decimal(5)) == Decimal(1000)


def test_a_drip_lot_costs_its_net_amount_in_the_currency() -> None:
    reinvested = drip(XTB, date(2026, 1, 2), AAPL, Decimal(1), Decimal(100), Decimal(15), nbp_rate=USD_4)

    [position] = open_positions([reinvested])

    assert position.fx_result(Decimal(5)) == Decimal(85)  # 85 USD net, 1 zł more each
