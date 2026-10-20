"""A made-up Portfolio for looking at the UI (``main.py --demo``): screenshots and visual changes, never real data.

All in PLN with Manual Prices and no Source Symbols, so the demo shows values without the network.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.instruments import InstrumentDraft, InstrumentType
from financial_app.domain.strategy import ClassTarget, Strategy
from financial_app.domain.transactions import TransactionType, buy_or_sell, deposit_or_withdrawal, dividend
from financial_app.persistence.accounts import add_account
from financial_app.persistence.instruments import add_instrument, list_asset_classes
from financial_app.persistence.strategies import save_strategy
from financial_app.persistence.transactions import add_transactions

# Made-up names, so a screenshot never passes for a real holding
_INSTRUMENTS = [
    # name, asset class, Manual Price, Instrument Type
    ("DEMO Akcje PL", "Akcje polskie", Decimal("48.20"), InstrumentType.STOCK),
    ("DEMO ETF Świat", "Akcje zagraniczne", Decimal("131.75"), InstrumentType.ETF),
    ("DEMO Obligacje", "Obligacje korporacyjne polskie", Decimal("101.30"), InstrumentType.BOND),
    ("DEMO Złoto", "Metale i surowce", Decimal("392.10"), InstrumentType.ETC),
]


def seed_demo_data(engine: Engine, today: date) -> None:
    """Fill the empty, migrated database at ``engine`` with two Accounts, a year of Transactions up to ``today`` and a
    Total Investment Strategy whose classes fall in each band colour."""
    classes = {asset_class.name: asset_class.id for asset_class in list_asset_classes(engine)}
    akcje, etf, obligacje, zloto = (
        add_instrument(
            engine, InstrumentDraft(name, classes[class_name], "PLN", manual_price=price, instrument_type=kind)
        ).id
        for name, class_name, price, kind in _INSTRUMENTS
    )
    regular = add_account(engine, AccountDraft("Konto maklerskie", "Dom Maklerski Demo", AccountType.REGULAR, ("PLN",)))
    ike = add_account(engine, AccountDraft("IKE", "Dom Maklerski Demo", AccountType.IKE, ("PLN",)))

    def day(days_ago: int) -> date:
        return today - timedelta(days=days_ago)

    add_transactions(
        engine,
        [
            deposit_or_withdrawal(regular.id, day(360), TransactionType.DEPOSIT, Decimal(20000)),
            buy_or_sell(regular.id, day(355), TransactionType.BUY, akcje, Decimal(150), Decimal("41.00"), Decimal(5)),
            buy_or_sell(regular.id, day(350), TransactionType.BUY, zloto, Decimal(10), Decimal("310.00"), Decimal(5)),
            buy_or_sell(
                regular.id, day(200), TransactionType.BUY, obligacje, Decimal(40), Decimal("99.50"), Decimal(5)
            ),
            dividend(regular.id, day(120), Decimal(300), Decimal(57), instrument_id=akcje),
            buy_or_sell(regular.id, day(60), TransactionType.SELL, akcje, Decimal(50), Decimal("47.10"), Decimal(5)),
            deposit_or_withdrawal(ike.id, day(300), TransactionType.DEPOSIT, Decimal(15000)),
            buy_or_sell(ike.id, day(295), TransactionType.BUY, etf, Decimal(60), Decimal("112.40"), Decimal(5)),
            deposit_or_withdrawal(ike.id, day(90), TransactionType.DEPOSIT, Decimal(8000)),
            buy_or_sell(ike.id, day(85), TransactionType.BUY, etf, Decimal(55), Decimal("124.90"), Decimal(5)),
        ],
    )
    # Shares of about 10, 32, 9 and 8 % against these targets: green, red, yellow, green
    targets = {
        "Akcje polskie": 10,
        "Akcje zagraniczne": 50,
        "Obligacje korporacyjne polskie": 15,
        "Metale i surowce": 5,
    }
    save_strategy(
        engine,
        Strategy(None, {classes[name]: ClassTarget(Decimal(percent)) for name, percent in targets.items()}),
    )
