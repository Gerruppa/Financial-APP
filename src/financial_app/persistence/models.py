"""ORM models. The schema itself is created and evolved only by Alembic migrations."""

from sqlalchemy import Boolean, ForeignKey, Integer, MetaData, String, Text
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
