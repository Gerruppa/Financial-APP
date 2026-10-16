"""The transaction dialog's rules without widgets (#111): the fields each Transaction Type shows and the Transaction its
fields describe, or the field that does not read."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.bond_valuation import BondData
from financial_app.domain.bonds import BondType
from financial_app.domain.currencies import MissingNbpRateError, NbpRate
from financial_app.domain.instruments import Instrument
from financial_app.domain.transaction_form import (
    SELL_CURRENCY,
    FormContext,
    FormError,
    FormState,
    FormTexts,
    Shown,
    TransactionForm,
)
from financial_app.domain.transactions import PLN, Transaction, TransactionError, TransactionType

TODAY = date(2026, 3, 10)
IKE, XTB, OLD, BONDS = 1, 2, 3, 4
CDR, AAPL, EDO, BTC = 10, 11, 12, 13
ACCOUNTS = [
    Account("mBank IKE", "mBank", AccountType.IKE, (PLN,), id=IKE),
    Account("XTB", "XTB", AccountType.REGULAR, (PLN, "USD"), fx_conversion_fee_percent=Decimal("0.5"), id=XTB),
    Account("Stare", "", AccountType.REGULAR, (PLN,), active=False, id=OLD),
    Account("Obligacje", "PKO", AccountType.BONDS, (PLN,), id=BONDS),
]


def _instrument(
    instrument_id: int, name: str, currency: str, asset_class: str = "Akcje polskie", decimals: int = 0
) -> Instrument:
    return Instrument(
        name, 1, currency, quantity_decimals=decimals, id=instrument_id, asset_class_name=asset_class,
        fallback_order=(),
    )  # fmt: skip


INSTRUMENTS = [
    _instrument(CDR, "CD Projekt", PLN),
    _instrument(AAPL, "Apple", "USD", "Akcje zagraniczne"),
    _instrument(EDO, "EDO0336", PLN, "Obligacje skarbowe polskie"),
    _instrument(BTC, "Bitcoin", "USD", "Kryptowaluty", decimals=8),
]
USD_RATE = NbpRate("USD", Decimal("4.0000"), date(2026, 3, 9), "045/A/NBP/2026")


def _rates(currency: str, day: date) -> NbpRate:
    if currency != "USD":
        raise MissingNbpRateError(f"Brak kursu NBP {currency}.")
    return USD_RATE


def _form(transactions: list[Transaction] | None = None, edited: Transaction | None = None) -> TransactionForm:
    return TransactionForm(
        FormContext(ACCOUNTS, INSTRUMENTS, transactions or [], {}, {}, BondData({}, []), _rates, edited)
    )


def _state(kind: TransactionType, account: int = IKE, **fields: object) -> FormState:
    texts = FormTexts(**{k: v for k, v in fields.items() if k in FormTexts.__dataclass_fields__})  # type: ignore[arg-type]
    choices = {k: v for k, v in fields.items() if k not in FormTexts.__dataclass_fields__}
    return FormState(account, kind, "02.03.2026", texts, **choices)  # type: ignore[arg-type]


def test_only_active_accounts_holding_pln_are_offered_unless_the_edited_transaction_is_on_one() -> None:
    assert list(_form().accounts) == [IKE, XTB, BONDS]

    edited = Transaction(OLD, date(2025, 1, 2), TransactionType.DEPOSIT, Decimal(100), id=1)
    assert list(_form(edited=edited).accounts) == [IKE, XTB, OLD, BONDS]


def test_a_new_form_opens_as_a_deposit_on_the_first_account_and_an_edit_with_its_own_fields() -> None:
    assert _form().initial_state(TODAY) == FormState(IKE, TransactionType.DEPOSIT, "10.03.2026", cash_currency=PLN)

    edited = Transaction(XTB, date(2026, 3, 2), TransactionType.WITHDRAWAL, Decimal("12.5"), "bankomat", id=7)
    start = _form(edited=edited).initial_state(TODAY)
    assert (start.account_id, start.kind, start.day) == (XTB, TransactionType.WITHDRAWAL, "02.03.2026")
    assert (start.texts.amount, start.texts.comment) == ("12,50", "bankomat")


def test_each_type_shows_its_own_fields() -> None:
    form = _form()

    deposit = form.layout(_state(TransactionType.DEPOSIT))
    assert (deposit.amount.visible, deposit.instrument_fields, deposit.target.visible) == (True, False, False)

    buy = form.layout(_state(TransactionType.BUY, instrument_id=CDR))
    assert (buy.amount.visible, buy.quantity.visible, buy.price.visible, buy.commission) == (False, True, True, True)
    assert (buy.price.label, buy.fx_rate.visible, buy.bond_mode) == ("Cena (zł)", False, True)

    split = form.layout(_state(TransactionType.SPLIT, instrument_id=CDR))
    assert (split.ratio, split.quantity.visible, split.price.visible) == (True, False, False)

    transfer = form.layout(_state(TransactionType.CASH_TRANSFER))
    assert transfer.target.visible and list(transfer.target.options) == [XTB, BONDS]
    assert transfer.target.value == XTB  # the first other Account until one is chosen


def test_a_foreign_buy_on_an_account_holding_the_currency_pays_from_it_by_default() -> None:
    layout = _form().layout(_state(TransactionType.BUY, XTB, instrument_id=AAPL))

    assert (layout.price.label, layout.fx_rate.label) == ("Cena (USD)", "Kurs USD/PLN")
    assert layout.paid_from.visible and layout.paid_from.value == "USD"
    assert not layout.convert.visible  # paid from USD cash, nothing to convert
    assert layout.auto_exchange


def test_paid_in_pln_on_an_account_with_a_conversion_fee_offers_the_broker_conversion() -> None:
    form = _form()
    state = _state(TransactionType.BUY, XTB, instrument_id=AAPL, paid_from=PLN)

    layout = form.layout(state)
    assert layout.convert.visible and layout.convert.label == "Prowizja XTB (przewalutowanie 0,50 %)"
    assert not layout.charged.visible

    converted = form.layout(replace(state, convert=True))
    assert converted.charged.visible and not converted.fx_rate.visible
    with pytest.raises(FormError, match="Podaj kwotę pobraną przez brokera.") as error:
        form.draft(replace(state, convert=True, texts=FormTexts(quantity="1", price="100")))
    assert error.value.field == "charged"


def test_a_foreign_buy_reads_with_the_nbp_rate_and_the_users_rate() -> None:
    state = _state(TransactionType.BUY, XTB, instrument_id=AAPL, quantity="2", price="100", fx_rate="3,9")

    draft = _form().draft(state)

    assert (draft.cash_currency, draft.nbp_rate, draft.fx_rate) == ("USD", USD_RATE, Decimal("3.9"))


def test_an_edited_foreign_trade_keeps_its_own_nbp_rate_while_its_date_stays() -> None:
    own = NbpRate("USD", Decimal("3.5"), date(2026, 2, 27), "040/A/NBP/2026")
    edited = Transaction(
        XTB, date(2026, 3, 2), TransactionType.BUY, Decimal(700), instrument_id=AAPL, quantity=Decimal(2),
        price=Decimal(100), nbp_rate=own, cash_currency="USD", id=5,
    )  # fmt: skip
    form = _form(edited=edited)
    state = form.initial_state(TODAY)

    assert form.draft(state).nbp_rate == own
    assert form.draft(replace(state, day="03.03.2026")).nbp_rate == USD_RATE


def test_interest_is_a_dividend_without_an_instrument_in_a_cash_currency_of_the_account() -> None:
    form = _form()

    layout = form.layout(_state(TransactionType.DIVIDEND, XTB, dividend_currency="USD"))
    assert layout.dividend_currency.visible and list(layout.dividend_currency.options) == [PLN, "USD"]
    assert layout.gross.label == "Kwota brutto (USD)"

    draft = form.draft(_state(TransactionType.DIVIDEND, XTB, dividend_currency="USD", gross="10", withholding_tax="2"))
    assert (draft.instrument_id, draft.dividend_currency, draft.cash_currency) == (None, "USD", "USD")
    # A currency the Account does not hold falls back to PLN
    unheld = _state(TransactionType.DIVIDEND, XTB, dividend_currency="CHF", gross="10")
    assert form.net_text(unheld) == "Netto: 10,00\xa0zł"


def test_a_currency_exchange_offers_the_accounts_currencies_and_the_common_ones_to_buy() -> None:
    form = _form()

    buying = form.layout(_state(TransactionType.CURRENCY_EXCHANGE, IKE))
    assert list(buying.exchange_currency.options) == ["USD", "EUR"]
    assert buying.direction.options["buy"] == "PLN → USD"

    selling = form.layout(_state(TransactionType.CURRENCY_EXCHANGE, IKE, direction=SELL_CURRENCY))
    assert selling.exchange_currency.value is None
    with pytest.raises(TransactionError, match="To konto nie ma waluty obcej"):
        form.draft(_state(TransactionType.CURRENCY_EXCHANGE, IKE, direction=SELL_CURRENCY))


def test_a_field_that_does_not_read_is_named() -> None:
    form = _form()

    with pytest.raises(FormError) as day:
        form.draft(replace(_state(TransactionType.DEPOSIT, amount="10"), day="2.3"))
    with pytest.raises(FormError) as amount:
        form.draft(_state(TransactionType.DEPOSIT, amount="dziesięć"))
    with pytest.raises(FormError) as instrument:
        form.draft(_state(TransactionType.BUY, quantity="1", price="1"))

    assert (day.value.field, amount.value.field, instrument.value.field) == ("day", "amount", "instrument")
    assert str(amount.value) == "Kwota musi być liczbą, np. 1 000,50."


def test_a_cost_on_an_account_holding_a_foreign_currency_may_be_paid_from_it() -> None:
    form = _form()

    assert not form.layout(_state(TransactionType.COST, IKE)).cash_currency.visible
    layout = form.layout(_state(TransactionType.COST, XTB, cash_currency="USD"))
    assert layout.cash_currency.visible and layout.amount.label == "Kwota (USD)"

    draft = form.draft(_state(TransactionType.COST, XTB, cash_currency="USD", amount="5"))
    assert (draft.cash_currency, draft.quantity, draft.actual_amount) == ("USD", Decimal(5), Decimal(20))


def test_a_deposit_on_an_account_holding_a_foreign_currency_may_be_in_it_at_the_users_or_the_nbp_rate() -> None:
    form = _form()

    pln = form.layout(_state(TransactionType.DEPOSIT, XTB))
    assert pln.cash_currency.visible and pln.cash_currency.value == PLN and not pln.fx_rate.visible
    assert not form.layout(_state(TransactionType.DEPOSIT, IKE)).cash_currency.visible
    usd = form.layout(_state(TransactionType.WITHDRAWAL, XTB, cash_currency="USD"))
    assert (usd.amount.label, usd.fx_rate.visible, usd.fx_rate.label) == ("Kwota (USD)", True, "Kurs USD/PLN")
    assert usd.fx_rate.hint == "Puste = kurs NBP z dnia roboczego przed datą"
    # A Cost in a foreign currency counts at the NBP Rate only
    assert not form.layout(_state(TransactionType.COST, XTB, cash_currency="USD")).fx_rate.visible

    at_nbp = form.draft(_state(TransactionType.DEPOSIT, XTB, cash_currency="USD", amount="100"))
    assert (at_nbp.cash_currency, at_nbp.quantity, at_nbp.actual_amount) == ("USD", Decimal(100), Decimal(400))
    own = form.draft(_state(TransactionType.WITHDRAWAL, XTB, cash_currency="USD", amount="100", fx_rate="3,9"))
    assert (own.fx_rate, own.nbp_rate, own.actual_amount) == (Decimal("3.9"), USD_RATE, Decimal(390))


def test_an_edited_foreign_deposit_opens_with_its_amount_rate_and_own_nbp_rate() -> None:
    own = NbpRate("USD", Decimal("3.5"), date(2026, 2, 27), "040/A/NBP/2026")
    edited = Transaction(
        XTB, date(2026, 3, 2), TransactionType.DEPOSIT, Decimal(360), quantity=Decimal(100), fx_rate=Decimal("3.6"),
        nbp_rate=own, cash_currency="USD", id=5,
    )  # fmt: skip
    form = _form(edited=edited)
    state = form.initial_state(TODAY)

    assert (state.cash_currency, state.texts.amount, state.texts.fx_rate) == ("USD", "100,00", "3,60")
    assert form.draft(replace(state, texts=replace(state.texts, fx_rate=""))).nbp_rate == own
    assert form.draft(replace(state, day="03.03.2026")).nbp_rate == USD_RATE


def test_the_bond_mode_buys_the_series_the_type_and_date_give_at_the_issue_price() -> None:
    form = _form()
    state = _state(TransactionType.BUY, BONDS, bond_mode=True, bond_type=BondType.COI)

    layout = form.layout(state)
    assert layout.bond_fields and not layout.instrument and layout.quantity.label == "Liczba obligacji"
    assert layout.series.value == "COI0330"
    assert layout.series_text == "Seria COI0330 · jeszcze nie ma jej w pliku MF"
    assert (form.series_to_buy(state), form.bond_price(state)) == ("COI0330", "100,00")
    assert form.series_to_buy(replace(state, series_pick="COI0230")) == "COI0230"
    assert form.bond_mode_for(BONDS) and not form.bond_mode_for(IKE)

    with pytest.raises(FormError, match="Data musi mieć postać"):
        form.series_to_buy(replace(state, day=""))


def test_a_sell_of_a_bond_series_picks_its_lot_the_oldest_by_default() -> None:
    bought = [
        Transaction(
            BONDS,
            date(2026, 1, day),
            TransactionType.BUY,
            Decimal(1000),
            instrument_id=EDO,
            quantity=Decimal(10),
            price=Decimal(100),
            id=day,
        )  # fmt: skip
        for day in (5, 7)
    ]
    form = _form(bought)
    state = _state(TransactionType.SELL, BONDS, instrument_id=EDO)

    layout = form.layout(state)
    assert layout.lot.visible and list(layout.lot.options) == [5, 7]
    assert layout.lot.options[5] == "05.01.2026 · 10 szt. · po 100,00\xa0zł"
    assert layout.lot.value == 5
    assert layout.withholding_tax.label == "Podatek pobrany (zł)"
    assert form.lot_quantity(replace(state, lot_id=7)) == "10"

    draft = form.draft(replace(state, lot_id=7, texts=FormTexts(quantity="4", price="101", withholding_tax="0,19")))
    assert (draft.lot_id, draft.withholding_tax, draft.actual_amount) == (7, Decimal("0.19"), Decimal("403.81"))
    assert form.net_text(replace(state, texts=FormTexts(quantity="4", price="101", commission="1"))) == (
        "Wypłata netto: 403,00\xa0zł"
    )


def test_a_buy_proposes_whole_units_for_the_amount_to_spend_less_the_commission() -> None:
    form = _form()
    state = _state(TransactionType.BUY, instrument_id=CDR, spend="1000", price="45", commission="5")

    assert form.layout(state).spend == Shown(True, "Kwota do wydania (zł)")
    # (1000 − 5) ÷ 45 = 22.1
    assert form.proposed_quantity(state) == "22"
    assert form.proposed_quantity(replace(state, texts=replace(state.texts, price=""))) is None
    assert not form.layout(_state(TransactionType.SELL, instrument_id=CDR)).spend.visible


def test_a_foreign_buy_paid_in_pln_converts_the_amount_at_the_users_rate_else_the_nbp_rate() -> None:
    form = _form()
    state = _state(TransactionType.BUY, instrument_id=BTC, spend="1000", price="60000", commission="10")

    # 990 zł ÷ 4,00 ÷ 60 000, rounded down to the Instrument's 8 decimal places
    assert form.proposed_quantity(state) == "0,004125"
    # 990 zł ÷ 3,95 = 250,6329… USD ÷ 60 000
    assert form.proposed_quantity(replace(state, texts=replace(state.texts, fx_rate="3,95"))) == "0,00417721"


def test_a_broker_conversion_raises_the_rate_by_the_accounts_fee() -> None:
    state = _state(TransactionType.BUY, XTB, instrument_id=BTC, paid_from=PLN, convert=True, spend="1000", price="100")

    # 1000 zł ÷ (4,00 × 1,005) ÷ 100
    assert _form().proposed_quantity(state) == "2,48756218"


def test_paid_from_foreign_cash_the_amount_is_in_that_currency_and_the_pln_commission_stays_apart() -> None:
    form = _form()
    state = _state(TransactionType.BUY, XTB, instrument_id=AAPL, spend="1000", price="300", commission="5")

    assert form.layout(state).spend.label == "Kwota do wydania (USD)"
    assert form.proposed_quantity(state) == "3"


def test_the_bond_mode_proposes_bonds_at_their_price() -> None:
    state = _state(TransactionType.BUY, bond_mode=True, spend="1050", price="100")

    assert _form().proposed_quantity(state) == "10"
