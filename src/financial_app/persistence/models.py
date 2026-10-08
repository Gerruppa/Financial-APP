"""ORM models. The schema itself is created and evolved only by Alembic migrations."""

import datetime as dt

from sqlalchemy import Boolean, Date, ForeignKey, Integer, MetaData, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Deterministic constraint names so SQLite batch migrations can alter them later
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class AppSetting(Base):
    """A key/value application setting (e.g. the last View Scope)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class AccountRow(Base):
    """An Account (spec 3.1). The ``Row`` suffix keeps it apart from ``domain.accounts.Account``, its in-memory form."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NOCASE makes SQLite reject "XTB" next to "xtb"; the repository also checks non-ASCII letters
    name: Mapped[str] = mapped_column(String(100, collation="NOCASE"), unique=True)
    broker: Mapped[str] = mapped_column(String(100))
    account_type: Mapped[str] = mapped_column(String(20))
    # Stored as text so the percentage keeps its exact decimal value (SQLite has no DECIMAL)
    fx_conversion_fee_percent: Mapped[str | None] = mapped_column(String(20))
    exclude_fx_result: Mapped[bool] = mapped_column(Boolean)
    active: Mapped[bool] = mapped_column(Boolean)

    cash_currencies: Mapped[list[AccountCashCurrency]] = relationship(
        cascade="all, delete-orphan", order_by="AccountCashCurrency.position"
    )


class AccountCashCurrency(Base):
    """One Cash Currency of an Account; ``position`` keeps the order the user entered them in."""

    __tablename__ = "account_cash_currencies"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)


class TransactionRow(Base):
    """A Transaction (spec 3.3); ``domain.transactions.Transaction`` is its in-memory form.

    Tax Amount and Origin join in later migrations (issues #15, #20).
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date)
    transaction_type: Mapped[str] = mapped_column(String(20))
    # PLN, as exact decimal text like the FX Conversion Fee
    actual_amount: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str] = mapped_column(Text)


class AssetClassRow(Base):
    """An Asset Class (spec 3.2); ``position`` keeps the sheet's order, with classes the user adds at the end."""

    __tablename__ = "asset_classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100, collation="NOCASE"), unique=True)
    position: Mapped[int] = mapped_column(Integer)


class InstrumentRow(Base):
    """An Instrument (spec 3.2); ``domain.instruments.Instrument`` is its in-memory form."""

    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200, collation="NOCASE"), unique=True)
    asset_class_id: Mapped[int] = mapped_column(ForeignKey("asset_classes.id"), index=True)
    quote_currency: Mapped[str] = mapped_column(String(3))
    market: Mapped[str] = mapped_column(String(100))
    # In the quote currency, as exact decimal text like the FX Conversion Fee
    manual_price: Mapped[str | None] = mapped_column(String(30))

    asset_class: Mapped[AssetClassRow] = relationship()
