"""The Dashboard's totals, Account table and currency exposure (issue #72, spec section 5)."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.bond_valuation import BondData
from financial_app.domain.bonds import BondSeries, CpiReading, SeriesTerms
from financial_app.domain.currencies import NbpRate
from financial_app.domain.dashboard import dashboard
from financial_app.domain.instruments import Instrument
from financial_app.domain.portfolio_history import DayValue
from financial_app.domain.transactions import TransactionDraft, TransactionType, buy_or_sell, currency_exchange

IKE, XTB = 1, 2
PZU, AAPL = 10, 20
TODAY = date(2026, 1, 31)
USD_RATE = NbpRate("USD", Decimal(4), date(2026, 1, 1), "1/A/NBP/2026")


def _account(account_id: int, name: str, exclude_fx_result: bool = False) -> Account:
    return Account(name, "", AccountType.REGULAR, ("PLN",), exclude_fx_result=exclude_fx_result, id=account_id)


ACCOUNTS = [_account(IKE, "IKE"), _account(XTB, "XTB", exclude_fx_result=True)]


def _instrument(instrument_id: int, currency: str = "PLN") -> Instrument:
    return Instrument("X", 1, currency, id=instrument_id, asset_class_name="Akcje", fallback_order=())


INSTRUMENTS = {PZU: _instrument(PZU), AAPL: _instrument(AAPL, "USD")}


def _deposit(amount: str, day: int = 1, account: int = IKE) -> TransactionDraft:
    return TransactionDraft(account, date(2026, 1, day), TransactionType.DEPOSIT, Decimal(amount))


def _buy(quantity: str, price: str, *, day: int = 2, fee: str = "0", account: int = IKE) -> TransactionDraft:
    return buy_or_sell(
        account, date(2026, 1, day), TransactionType.BUY, PZU, Decimal(quantity), Decimal(price), Decimal(fee)
    )


def _today(net_deposits: str, accounts: dict[int, str]) -> DayValue:
    """History's last day; the Dashboard takes only the Net Deposits from it."""
    return DayValue(
        TODAY,
        {},
        {},
        Decimal(net_deposits),
        {account_id: Decimal(amount) for account_id, amount in accounts.items()},
        frozenset(),
    )


def test_totals_value_cash_and_positions_at_todays_price() -> None:
    transactions = [_deposit("1000"), _buy("10", "50", fee="5")]

    board = dashboard(transactions, ACCOUNTS, INSTRUMENTS, {PZU: Decimal(60)}, {}, [_today("1000", {IKE: "1000"})])

    totals = board.totals
    assert totals.net_deposits == Decimal(1000)
    assert totals.cash == Decimal(495)
    assert totals.open_positions == Decimal(600)
    assert totals.value == Decimal(1095)
    assert totals.unrealized == Decimal(95)
    assert totals.realized == Decimal(0)
    assert totals.dividends == Decimal(0)
    assert totals.costs == Decimal(5)


def _exchange(foreign: str, pln: str, *, day: int = 2, account: int = IKE, to_pln: bool = False) -> TransactionDraft:
    return currency_exchange(account, date(2026, 1, day), "USD", Decimal(foreign), Decimal(pln), to_pln=to_pln)


def test_foreign_cash_counts_in_open_positions_and_its_fx_result_unless_the_account_excludes_it() -> None:
    # 250 USD bought for 1000 PLN on each Account, worth 1050 PLN at 4.20; XTB excludes its FX result
    transactions = [_deposit("1000"), _exchange("250", "1000"), _deposit("1000", account=XTB)]
    transactions.append(_exchange("250", "1000", account=XTB))

    totals = dashboard(transactions, ACCOUNTS, INSTRUMENTS, {}, {"USD": Decimal("4.2")}, None).totals

    assert totals.cash == Decimal(0)
    assert totals.open_positions == Decimal(2100)
    assert totals.unrealized == Decimal(50)


def test_realised_fx_result_counts_in_the_realised_result_unless_the_account_excludes_it() -> None:
    # 100 of 250 USD bought at 4.00 sold back at 4.40 realise 40 PLN on each Account; XTB excludes its FX result
    transactions = []
    for account in (IKE, XTB):
        transactions += [_deposit("1000", account=account), _exchange("250", "1000", account=account)]
        transactions.append(_exchange("100", "440", day=3, account=account, to_pln=True))

    totals = dashboard(transactions, ACCOUNTS, INSTRUMENTS, {}, {"USD": Decimal(4)}, None).totals

    assert totals.realized == Decimal(40)


def test_each_account_has_a_row_and_an_account_scope_shows_only_that_account() -> None:
    # A Cash Transfer of 200 from IKE to XTB: Total's Net Deposits stay 1500, the Accounts' move with it
    transactions = [_deposit("1000"), _deposit("500", account=XTB), _buy("10", "50")]
    transactions.append(
        TransactionDraft(IKE, date(2026, 1, 3), TransactionType.CASH_TRANSFER, Decimal(200), target_account_id=XTB)
    )
    history = [_today("1500", {IKE: "800", XTB: "700"})]

    total = dashboard(transactions, ACCOUNTS, INSTRUMENTS, {PZU: Decimal(60)}, {}, history)
    xtb = dashboard(transactions, ACCOUNTS, INSTRUMENTS, {PZU: Decimal(60)}, {}, history, account_id=XTB)

    assert [(row.account.name, row.totals.net_deposits, row.totals.value) for row in total.accounts] == [
        ("IKE", Decimal(800), Decimal(900)),
        ("XTB", Decimal(700), Decimal(700)),
    ]
    assert (total.totals.net_deposits, total.totals.value) == (Decimal(1500), Decimal(1600))
    assert [row.account.name for row in xtb.accounts] == ["XTB"]
    assert (xtb.totals.net_deposits, xtb.totals.value) == (Decimal(700), Decimal(700))


def test_currency_exposure_groups_positions_by_quote_currency_with_the_cash_of_each_currency() -> None:
    # PLN: 300 cash + 10 PZU at 60; USD: 2 AAPL at 450 PLN + 100 USD at 4.50
    transactions = [_deposit("2000"), _buy("10", "50"), _exchange("100", "400")]
    transactions.append(
        buy_or_sell(IKE, date(2026, 1, 2), TransactionType.BUY, AAPL, Decimal(2), Decimal(100), nbp_rate=USD_RATE)
    )
    prices = {PZU: Decimal(60), AAPL: Decimal(450)}

    board = dashboard(transactions, ACCOUNTS, INSTRUMENTS, prices, {"USD": Decimal("4.5")}, None)

    assert [(c.currency, c.value, c.share) for c in board.currencies] == [
        ("USD", Decimal(1350), Decimal("0.6")),
        ("PLN", Decimal(900), Decimal("0.4")),
    ]


def test_allocation_gives_each_asset_class_share_with_pln_and_foreign_cash_in_their_own_classes() -> None:
    # Gotówka: 300; Akcje: 10 PZU at 60 + 2 AAPL at 450 PLN; Waluty: 100 USD at 4.50; XTB is outside the scope
    transactions = [_deposit("2000"), _buy("10", "50"), _exchange("100", "400"), _deposit("500", account=XTB)]
    transactions.append(
        buy_or_sell(IKE, date(2026, 1, 2), TransactionType.BUY, AAPL, Decimal(2), Decimal(100), nbp_rate=USD_RATE)
    )
    prices = {PZU: Decimal(60), AAPL: Decimal(450)}

    board = dashboard(transactions, ACCOUNTS, INSTRUMENTS, prices, {"USD": Decimal("4.5")}, None, IKE)

    assert [(c.asset_class, c.value, c.share) for c in board.classes] == [
        ("Akcje", Decimal(1500), Decimal("0.6666666666666666666666666667")),
        ("Waluty", Decimal(450), Decimal("0.2")),
        ("Gotówka", Decimal(300), Decimal("0.1333333333333333333333333333")),
    ]


def test_xirr_ends_at_todays_dashboard_value_not_historys() -> None:
    # History values PZU at cost (no history price), the Dashboard at 60: 1000 paid in on 1.01 is worth 1100 on 31.01
    history = [
        DayValue(date(2026, 1, 1), {IKE: Decimal(1000)}, {}, Decimal(1000), {IKE: Decimal(1000)}, frozenset()),
        DayValue(TODAY, {IKE: Decimal(1000)}, {}, Decimal(1000), {IKE: Decimal(1000)}, frozenset({PZU})),
    ]
    transactions = [_deposit("1000"), _buy("10", "50")]

    board = dashboard(
        transactions, ACCOUNTS, INSTRUMENTS, {PZU: Decimal(60)}, {}, history, period=(date(2026, 1, 1), TODAY)
    )

    assert board.totals.xirr == pytest.approx(Decimal("2.1886"), abs=Decimal("0.0001"))


def test_each_account_row_has_its_own_xirr_to_its_value_today() -> None:
    # IKE: 1000 in on 1.01 worth 1100 on 31.01; XTB: 500 in on 1.01, still 500
    history = [
        DayValue(
            date(2026, 1, 1),
            {IKE: Decimal(1000), XTB: Decimal(500)},
            {},
            Decimal(1500),
            {IKE: Decimal(1000), XTB: Decimal(500)},
            frozenset(),
        ),
        DayValue(
            TODAY,
            {IKE: Decimal(1000), XTB: Decimal(500)},
            {},
            Decimal(1500),
            {IKE: Decimal(1000), XTB: Decimal(500)},
            frozenset({PZU}),
        ),
    ]
    transactions = [_deposit("1000"), _deposit("500", account=XTB), _buy("10", "50")]

    board = dashboard(
        transactions, ACCOUNTS, INSTRUMENTS, {PZU: Decimal(60)}, {}, history, period=(date(2026, 1, 1), TODAY)
    )

    ike, xtb = board.accounts
    assert ike.totals.xirr == pytest.approx(Decimal("2.1886"), abs=Decimal("0.0001"))
    assert xtb.totals.xirr == Decimal(0)


def test_an_inactive_account_shows_only_while_it_still_holds_something() -> None:
    closed = Account("Stare", "", AccountType.REGULAR, ("PLN",), active=False, id=3)
    emptied = Account("Puste", "", AccountType.REGULAR, ("PLN",), active=False, id=4)
    transactions = [_deposit("100", account=3), _deposit("100", account=4)]
    transactions.append(TransactionDraft(4, date(2026, 1, 2), TransactionType.WITHDRAWAL, Decimal(100)))

    board = dashboard(transactions, [*ACCOUNTS, closed, emptied], INSTRUMENTS, {}, {}, None)

    assert [row.account.name for row in board.accounts] == ["IKE", "XTB", "Stare"]


def test_the_allocation_comes_by_account_and_by_instrument_for_the_investment_strategy() -> None:
    transactions = [_deposit("1000"), _buy("10", "50"), _deposit("300", account=XTB)]

    board = dashboard(transactions, ACCOUNTS, INSTRUMENTS, {PZU: Decimal(60)}, {}, None)

    assert board.holdings == {"Akcje": {PZU: Decimal(600)}}
    assert board.account_classes == {
        IKE: {"Akcje": Decimal(600), "Gotówka": Decimal(500)},
        XTB: {"Gotówka": Decimal(300)},
    }


def test_a_regular_account_estimates_belka_on_its_unrealised_gains_at_the_tax_cost() -> None:
    # IKE is a real IKE here: no tax; on XTB 10 PZU bought for 505 zł are worth 600 zł, so 19% of 95 zł
    ike = Account("IKE", "", AccountType.IKE, ("PLN",), id=IKE)
    transactions = [_deposit("1000"), _buy("10", "50"), _deposit("1000", account=XTB)]
    transactions.append(_buy("10", "50", fee="5", account=XTB))

    board = dashboard(transactions, [ike, ACCOUNTS[1]], INSTRUMENTS, {PZU: Decimal(60)}, {}, None)

    ike_row, xtb_row = board.accounts
    assert ike_row.totals.estimated_tax == Decimal(0)
    assert xtb_row.totals.estimated_tax == Decimal("18.05")
    assert board.totals.estimated_tax == Decimal("18.05")


def test_losses_on_one_regular_account_offset_gains_on_another_in_the_total() -> None:
    # PIT-38 is one return: IKE (Regular here) gains 100 zł, XTB loses 60 zł, so Total estimates 19% of 40 zł
    transactions = [_deposit("1000"), _buy("10", "50"), _deposit("1000", account=XTB), _buy("10", "66", account=XTB)]

    board = dashboard(transactions, ACCOUNTS, INSTRUMENTS, {PZU: Decimal(60)}, {}, None)

    ike_row, xtb_row = board.accounts
    assert (ike_row.totals.estimated_tax, xtb_row.totals.estimated_tax) == (Decimal(19), Decimal(0))
    assert board.totals.estimated_tax == Decimal("7.60")


def test_the_profit_is_the_value_less_the_net_deposits_and_waits_for_history() -> None:
    transactions = [_deposit("1000"), _buy("10", "50")]

    with_history = dashboard(
        transactions, ACCOUNTS, INSTRUMENTS, {PZU: Decimal(60)}, {}, [_today("1000", {IKE: "1000"})]
    )
    loading = dashboard(transactions, ACCOUNTS, INSTRUMENTS, {PZU: Decimal(60)}, {}, None)

    assert with_history.totals.profit == Decimal(100)
    assert with_history.accounts[0].totals.profit == Decimal(100)
    assert loading.totals.profit is None


def test_each_account_row_has_its_twr_over_the_period() -> None:
    # IKE grows from 1000 to 1100 (today's value, 10 PZU at 60) with no flows in between: a TWR of 10%
    history = [
        DayValue(date(2026, 1, 1), {IKE: Decimal(1000)}, {}, Decimal(1000), {IKE: Decimal(1000)}, frozenset()),
        DayValue(TODAY, {IKE: Decimal(1100)}, {}, Decimal(1000), {IKE: Decimal(1000)}, frozenset()),
    ]

    transactions = [_deposit("1000"), _buy("10", "50")]

    board = dashboard(
        transactions, ACCOUNTS, INSTRUMENTS, {PZU: Decimal(60)}, {}, history, period=(date(2026, 1, 1), TODAY)
    )

    assert board.accounts[0].totals.twr == Decimal("0.1")
    assert board.totals.twr == Decimal("0.1")


def test_the_dashboard_carries_the_profit_by_source() -> None:
    transactions = [_deposit("1000"), _buy("10", "50", fee="5")]

    board = dashboard(transactions, ACCOUNTS, INSTRUMENTS, {PZU: Decimal(60)}, {}, None)

    assert (board.sources.price, board.sources.costs) == (Decimal(100), Decimal(-5))


def test_a_bond_series_deducts_its_fee_and_withheld_tax_after_tax_not_offset_by_other_losses() -> None:
    # 10 EDO0535 bought on 22.05.2025 are worth 107.66 zł a bond on 8.10.2026 and would net 103.77 zł: the 3 zł fee
    # and 0.89 zł of Belka withheld at redemption, which a loss on the shares (19 zł on XTB, Regular) never offsets
    edo = Instrument("EDO0535", 1, "PLN", id=30, asset_class_name="Obligacje skarbowe polskie", fallback_order=())
    terms = SeriesTerms(
        "EDO0535",
        "PL0",
        date(2025, 5, 1),
        date(2025, 5, 31),
        Decimal(100),
        Decimal("99.9"),
        Decimal("0.02"),
        (Decimal("0.0565"),) + (None,) * 9,
        (),
    )
    bonds = BondData({30: BondSeries(30, "EDO0535", terms)}, (CpiReading(2026, 3, Decimal("103.0"), None),))
    price = bonds.price(30, date(2026, 10, 8))
    bonds_account = Account("Obligacje", "", AccountType.BONDS, ("PLN",), id=3)
    transactions = [
        TransactionDraft(3, date(2025, 5, 22), TransactionType.DEPOSIT, Decimal(1000)),
        buy_or_sell(3, date(2025, 5, 22), TransactionType.BUY, 30, Decimal(10), Decimal(100)),
        _deposit("1000", account=XTB),
        _buy("10", "62", account=XTB),
    ]

    board = dashboard(
        transactions, [ACCOUNTS[1], bonds_account], INSTRUMENTS | {30: edo}, {PZU: Decimal(60), 30: price}, {}, None
    )

    xtb_row, bonds_row = board.accounts
    assert bonds_row.totals.open_positions == Decimal("1076.60")
    assert bonds_row.totals.estimated_tax == Decimal("38.90")
    assert xtb_row.totals.estimated_tax == Decimal(0)
    assert board.totals.estimated_tax == Decimal("38.90")
