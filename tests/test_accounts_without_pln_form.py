"""The transaction dialog's rules on an Account without PLN (issue #124): it offers only what the Account's own cash
can pay, and a trade's commission is in that cash."""

from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.bond_valuation import BondData
from financial_app.domain.currencies import MissingNbpRateError, NbpRate
from financial_app.domain.instruments import Instrument
from financial_app.domain.transaction_form import FormContext, FormState, FormTexts, Shown, TransactionForm
from financial_app.domain.transactions import PLN, TransactionError, TransactionType

IKE, REVOLUT = 1, 2
CDR, AAPL = 10, 11
ACCOUNTS = [
    Account("mBank IKE", "mBank", AccountType.IKE, (PLN,), id=IKE),
    Account("Revolut", "Revolut", AccountType.REGULAR, ("USD",), id=REVOLUT),
]
INSTRUMENTS = [
    Instrument("CD Projekt", 1, PLN, id=CDR, asset_class_name="Akcje polskie", fallback_order=()),
    Instrument("Apple", 1, "USD", id=AAPL, asset_class_name="Akcje zagraniczne", fallback_order=()),
]
USD_RATE = NbpRate("USD", Decimal("4.0000"), date(2026, 3, 9), "045/A/NBP/2026")


def _rates(currency: str, day: date) -> NbpRate:
    if currency != "USD":
        raise MissingNbpRateError(f"Brak kursu NBP {currency}.")
    return USD_RATE


def _form() -> TransactionForm:
    return TransactionForm(FormContext(ACCOUNTS, INSTRUMENTS, [], {}, {}, BondData({}, []), _rates))


def _state(kind: TransactionType, account: int = REVOLUT, **fields: object) -> FormState:
    texts = FormTexts(**{k: v for k, v in fields.items() if k in FormTexts.__dataclass_fields__})  # type: ignore[arg-type]
    choices = {k: v for k, v in fields.items() if k not in FormTexts.__dataclass_fields__}
    return FormState(account, kind, "10.03.2026", texts, **choices)  # type: ignore[arg-type]


def test_buy_on_an_account_without_pln_pays_from_its_dollars_with_a_usd_commission() -> None:
    form = _form()
    assert list(form.accounts) == [IKE, REVOLUT]
    state = _state(TransactionType.BUY, instrument_id=AAPL, quantity="10", price="100", commission="2,50")

    layout = form.layout(state)
    assert layout.commission == Shown(True, "Prowizja (USD)")
    assert list(layout.paid_from.options) == ["USD"]
    assert (layout.convert.visible, layout.auto_exchange) == (False, False)

    buy = form.draft(state)
    assert (buy.cash_currency, buy.commission_currency, buy.commission) == ("USD", "USD", Decimal("2.50"))
    assert buy.foreign_cash_change == Decimal("-1002.50")


def test_an_account_holding_pln_keeps_its_commission_in_pln() -> None:
    form = _form()
    state = _state(TransactionType.BUY, IKE, instrument_id=CDR, quantity="1", price="100", commission="5")

    assert form.layout(state).commission == Shown(True, "Prowizja (zł)")
    assert form.draft(state).commission_currency == PLN


def test_no_exchange_on_an_account_without_pln_nor_a_pln_cash_transfer_into_it() -> None:
    form = _form()

    offered = form.kinds(_state(TransactionType.DEPOSIT))
    assert TransactionType.CURRENCY_EXCHANGE not in offered
    # A Cash Transfer in its own currency is (#125)
    assert TransactionType.CASH_TRANSFER in offered and TransactionType.SECURITY_TRANSFER in offered
    assert list(form.kinds(_state(TransactionType.DEPOSIT, IKE))) == list(TransactionType)

    assert form.layout(_state(TransactionType.CASH_TRANSFER, IKE)).target.options == {}
    assert list(form.layout(_state(TransactionType.SECURITY_TRANSFER, IKE)).target.options) == [REVOLUT]


def test_cash_amounts_on_an_account_without_pln_are_in_its_own_currency() -> None:
    form = _form()

    deposit = form.layout(_state(TransactionType.DEPOSIT, amount="100"))
    assert (deposit.cash_currency.options, deposit.cash_currency.value) == ({"USD": "USD"}, "USD")
    assert deposit.amount.label == "Kwota (USD)"
    assert form.draft(_state(TransactionType.DEPOSIT, amount="100")).quantity == Decimal(100)

    interest = form.layout(_state(TransactionType.DIVIDEND, gross="10"))
    assert interest.dividend_currency.value == "USD"


def test_amount_to_spend_leaves_room_for_the_usd_commission() -> None:
    state = _state(TransactionType.BUY, instrument_id=AAPL, spend="1000", price="100", commission="2,50")

    assert _form().proposed_quantity(state) == "9"


def test_a_trade_in_a_currency_the_account_lacks_is_refused() -> None:
    state = _state(TransactionType.BUY, instrument_id=CDR, quantity="1", price="100")

    with pytest.raises(TransactionError, match="Konto Revolut nie ma waluty rachunku PLN"):
        _form().draft(state)
