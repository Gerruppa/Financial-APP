"""The examples the first Recurring Rule starts from (#275): a monthly Deposit to an IKE/IKZE Account, a monthly
ETF purchase (a standing order at the broker), a Cash Transfer between two Accounts, or the user's own ("Własna").

Each pre-fills a new rule's dialog as ``RuleDefaults``, from the next occurrence of its day, so that it brings no
backlog of Drafts.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.recurring import Frequency, RuleDefaults, first_occurrence_after
from financial_app.domain.transactions import PLN, TransactionType


@dataclass(frozen=True)
class RuleExample:
    """An example: its label and description in the window, and the rule it pre-fills. ``day_of_month`` ``None`` is
    today's; ``account_types`` are the Account types it prefers, first found first."""

    key: str
    label: str
    description: str
    name: str
    transaction_type: TransactionType
    amount: Decimal | None
    day_of_month: int | None
    account_types: tuple[AccountType, ...] = ()


RULE_EXAMPLES = (
    RuleExample(
        "deposit",
        "Miesięczna wpłata na IKE lub IKZE",
        "Przelew stały z banku, np. 10. dnia miesiąca.",
        "Wpłata IKE",
        TransactionType.DEPOSIT,
        Decimal(500),
        10,
        (AccountType.IKE, AccountType.IKZE),
    ),
    RuleExample(
        "etf",
        "Miesięczny zakup ETF",
        "Zlecenie stałe u brokera za stałą kwotę co miesiąc. Liczbę i cenę jednostek wpiszesz przy zatwierdzaniu.",
        "Zakup ETF",
        TransactionType.BUY,
        Decimal(500),
        12,
        (AccountType.IKE, AccountType.IKZE, AccountType.REGULAR),
    ),
    RuleExample(
        "transfer",
        "Transfer gotówki między kontami",
        "Co miesiąc z konta maklerskiego na IKE lub IKZE.",
        "Transfer na IKE",
        TransactionType.CASH_TRANSFER,
        Decimal(1000),
        1,
        (AccountType.REGULAR,),
    ),
)
CUSTOM = RuleExample(
    "custom",
    "Własna",
    "Bez przykładu: typ i pola wybierzesz sam.",
    "",
    TransactionType.DEPOSIT,
    None,
    None,
)


def example_defaults(example: RuleExample, today: date, accounts: Sequence[Account]) -> RuleDefaults:
    """What ``example`` pre-fills: its Account the first active one of a preferred type (else the first active one), a
    Cash Transfer's target the first other active Account (an IKE or IKZE first), monthly from the next occurrence."""
    active = [account for account in accounts if account.active]
    preferred = [a for kind in example.account_types for a in active if a.account_type is kind]
    source = next(iter(preferred + active), None)
    target = None
    if example.transaction_type is TransactionType.CASH_TRANSFER:
        others = [a for a in active if a is not source]
        wrappers = [a for a in others if a.account_type in (AccountType.IKE, AccountType.IKZE)]
        target = next(iter(wrappers + others), None)
    day = example.day_of_month or today.day
    return RuleDefaults(
        None if source is None else source.id,
        example.transaction_type,
        day,
        first_occurrence_after(day, Frequency.MONTHLY, today),
        amount=example.amount,
        currency=PLN,
        target_account_id=None if target is None else target.id,
    )
