"""The transaction dialog's rules for a Cash Transfer in a foreign currency (issue #125): its currency is one of the
source's, and it goes only to an Account holding that currency."""

from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.bond_valuation import BondData
from financial_app.domain.currencies import MissingNbpRateError, NbpRate
from financial_app.domain.transaction_form import FormContext, FormState, FormTexts, TransactionForm
from financial_app.domain.transactions import PLN, Transaction, TransactionType

IKE, XTB, REVOLUT = 1, 2, 3
ACCOUNTS = [
    Account("mBank IKE", "mBank", AccountType.IKE, (PLN,), id=IKE),
    Account("XTB", "XTB", AccountType.REGULAR, (PLN, "USD"), id=XTB),
    Account("Revolut", "Revolut", AccountType.REGULAR, ("USD",), id=REVOLUT),
]
USD_RATE = NbpRate("USD", Decimal("4.0000"), date(2026, 3, 9), "045/A/NBP/2026")


def _rates(currency: str, day: date) -> NbpRate:
    if currency != "USD":
        raise MissingNbpRateError(f"Brak kursu NBP {currency}.")
    return USD_RATE


def _form(edited: Transaction | None = None) -> TransactionForm:
    return TransactionForm(FormContext(ACCOUNTS, [], [], {}, {}, BondData({}, []), _rates, edited))


def _transfer(account: int = XTB, **choices: object) -> FormState:
    return FormState(account, TransactionType.CASH_TRANSFER, "10.03.2026", FormTexts(amount="100"), **choices)  # type: ignore[arg-type]


def test_a_transfer_is_in_pln_by_default_and_may_be_in_the_sources_foreign_currency() -> None:
    form = _form()

    pln = form.layout(_transfer())
    assert (pln.cash_currency.visible, list(pln.cash_currency.options), pln.cash_currency.value) == (
        True,
        [PLN, "USD"],
        PLN,
    )
    assert list(pln.target.options) == [IKE]

    usd = form.layout(_transfer(cash_currency="USD"))
    assert usd.amount.label == "Kwota (USD)"
    assert list(usd.target.options) == [REVOLUT]
    assert not usd.fx_rate.visible  # at the NBP Rate only

    draft = form.draft(_transfer(cash_currency="USD"))
    assert (draft.cash_currency, draft.quantity, draft.actual_amount) == ("USD", Decimal(100), Decimal("400.00"))
    assert draft.target_account_id == REVOLUT


def test_an_account_without_pln_transfers_its_own_currency() -> None:
    form = _form()

    assert TransactionType.CASH_TRANSFER in form.kinds(_transfer(REVOLUT))
    layout = form.layout(_transfer(REVOLUT))
    assert (layout.cash_currency.value, list(layout.target.options)) == ("USD", [XTB])


def test_an_edited_usd_transfer_opens_with_its_dollars() -> None:
    edited = Transaction(
        XTB, date(2026, 3, 10), TransactionType.CASH_TRANSFER, Decimal("400.00"),
        quantity=Decimal(100), nbp_rate=USD_RATE, cash_currency="USD", target_account_id=REVOLUT, id=5,
    )  # fmt: skip

    start = _form(edited).initial_state(date(2026, 3, 12))
    assert (start.texts.amount, start.cash_currency, start.target_id) == ("100,00", "USD", REVOLUT)
