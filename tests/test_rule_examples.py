"""The first Recurring Rule's examples (#275): what each pre-fills, and the occurrences its preview lists."""

from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.recurring import Frequency, RecurringRuleDraft, upcoming_occurrences
from financial_app.domain.rule_examples import CUSTOM, RULE_EXAMPLES, example_defaults
from financial_app.domain.transactions import TransactionType

# A Thursday
TODAY = date(2026, 10, 15)


def account(id: int, account_type: AccountType, name: str) -> Account:
    return Account(name, "Broker", account_type, ("PLN",), id=id)


REGULAR = account(1, AccountType.REGULAR, "Maklerskie")
IKE = account(2, AccountType.IKE, "IKE")


def test_the_examples_cover_a_deposit_a_buy_and_a_cash_transfer() -> None:
    kinds = [e.transaction_type for e in RULE_EXAMPLES]
    assert kinds == [TransactionType.DEPOSIT, TransactionType.BUY, TransactionType.CASH_TRANSFER]
    assert CUSTOM not in RULE_EXAMPLES


def test_the_deposit_example_prefers_an_ike_or_ikze_account() -> None:
    [deposit] = [e for e in RULE_EXAMPLES if e.transaction_type is TransactionType.DEPOSIT]
    defaults = example_defaults(deposit, TODAY, [REGULAR, IKE])
    assert defaults.account_id == IKE.id
    assert defaults.transaction_type is TransactionType.DEPOSIT
    assert defaults.amount == deposit.amount
    assert defaults.frequency is Frequency.MONTHLY
    # The next occurrence of its day, so no backlog of Drafts
    assert defaults.day_of_month == deposit.day_of_month
    assert defaults.start_date > TODAY


def test_an_example_falls_back_to_the_first_account() -> None:
    [deposit] = [e for e in RULE_EXAMPLES if e.transaction_type is TransactionType.DEPOSIT]
    assert example_defaults(deposit, TODAY, [REGULAR]).account_id == REGULAR.id
    assert example_defaults(deposit, TODAY, []).account_id is None


def test_the_cash_transfer_example_goes_to_another_account() -> None:
    [transfer] = [e for e in RULE_EXAMPLES if e.transaction_type is TransactionType.CASH_TRANSFER]
    defaults = example_defaults(transfer, TODAY, [REGULAR, IKE])
    assert defaults.account_id == REGULAR.id
    assert defaults.target_account_id == IKE.id
    assert example_defaults(transfer, TODAY, [REGULAR]).target_account_id is None


def test_an_inactive_account_is_never_proposed() -> None:
    closed = Account("IKE stare", "Broker", AccountType.IKE, ("PLN",), active=False, id=3)
    [deposit] = [e for e in RULE_EXAMPLES if e.transaction_type is TransactionType.DEPOSIT]
    assert example_defaults(deposit, TODAY, [closed, REGULAR]).account_id == REGULAR.id


def test_the_own_rule_starts_on_todays_day_of_the_month_with_no_amount() -> None:
    defaults = example_defaults(CUSTOM, TODAY, [REGULAR])
    assert (defaults.day_of_month, defaults.start_date, defaults.amount) == (15, date(2026, 11, 16), None)


def test_upcoming_occurrences_lists_the_first_few_from_the_start() -> None:
    rule = RecurringRuleDraft(
        "Wpłata IKE",
        IKE.id,
        TransactionType.DEPOSIT,
        Decimal(500),
        "PLN",
        Frequency.MONTHLY,
        10,
        date(2026, 11, 1),
    )
    # 10.01.2027 is a Sunday, moved to Monday
    assert upcoming_occurrences(rule, 3) == [date(2026, 11, 10), date(2026, 12, 10), date(2027, 1, 11)]


def test_upcoming_occurrences_stop_at_the_rules_end() -> None:
    rule = RecurringRuleDraft(
        "Wpłata IKE",
        IKE.id,
        TransactionType.DEPOSIT,
        Decimal(500),
        "PLN",
        Frequency.QUARTERLY,
        10,
        date(2026, 11, 1),
        end_date=date(2027, 3, 1),
    )
    assert upcoming_occurrences(rule, 3) == [date(2026, 11, 10), date(2027, 2, 10)]
