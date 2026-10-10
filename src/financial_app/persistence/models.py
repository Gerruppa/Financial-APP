"""ORM models. The schema itself is created and evolved only by Alembic migrations."""

import datetime as dt

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, MetaData, String, Text, false
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

    The Tax Amount is not stored: it follows from the stored NBP Rate.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date)
    transaction_type: Mapped[str] = mapped_column(String(20))
    # PLN, as exact decimal text like the FX Conversion Fee
    actual_amount: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str] = mapped_column(Text)
    # Buy and Sell: the Instrument, quantity, unit price and PLN commission, as exact decimal text; a Dividend may
    # have the Instrument, a DRIP has it and the quantity
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    quantity: Mapped[str | None] = mapped_column(String(30))
    price: Mapped[str | None] = mapped_column(String(30))
    commission: Mapped[str | None] = mapped_column(String(30))
    # Foreign-currency Buy, Sell, Dividend and DRIP only: the user's own rate (None means the NBP Rate) and the NBP
    # Rate (D-1)
    fx_rate: Mapped[str | None] = mapped_column(String(30))
    nbp_currency: Mapped[str | None] = mapped_column(String(3))
    nbp_rate: Mapped[str | None] = mapped_column(String(30))
    nbp_published_on: Mapped[dt.date | None] = mapped_column(Date)
    nbp_table: Mapped[str | None] = mapped_column(String(30))
    # The Cash Currency paid from or into: PLN, or the foreign one of a Currency Exchange or of a Buy or Sell paid
    # from foreign cash, or of a Dividend paid into it; ``to_pln`` marks an Exchange selling that currency (issue #16)
    cash_currency: Mapped[str] = mapped_column(String(3), server_default="PLN")
    to_pln: Mapped[bool] = mapped_column(Boolean, server_default=false())
    # Foreign-currency Buy and Sell paid in PLN only: the FX Conversion Fee % when the broker converted it; the fee in
    # PLN follows from it like the Tax Amount follows from the NBP Rate (issue #17)
    fx_conversion_fee_percent: Mapped[str | None] = mapped_column(String(20))
    # Dividend and DRIP only: the gross amount and the withholding tax, in the Dividend's currency (issue #18)
    gross: Mapped[str | None] = mapped_column(String(30))
    withholding_tax: Mapped[str | None] = mapped_column(String(30))
    # Cash and Security Transfer only: the Account it goes to (issue #19)
    target_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    # Split only: X:Y, every ``split_old`` units become ``split_new`` (issue #19)
    split_new: Mapped[int | None] = mapped_column(Integer)
    split_old: Mapped[int | None] = mapped_column(Integer)
    # Where it came from (spec 7): "manual" or "spreadsheet"; an imported one carries its row's fingerprint (issue #20)
    origin: Mapped[str] = mapped_column(String(20), server_default="manual")
    external_id: Mapped[str | None] = mapped_column(String(100), unique=True)


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
    source_symbols: Mapped[list[SourceSymbolRow]] = relationship(cascade="all, delete-orphan")


class SourceSymbolRow(Base):
    """An Instrument's Source Symbol in one Price Source (issue #30); ``source`` is a ``domain.prices`` key."""

    __tablename__ = "source_symbols"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(100))


class QuoteRow(Base):
    """An Instrument's Quote for ``day`` (issue #30); a later fetch on the same day replaces it."""

    __tablename__ = "quotes"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    day: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    # In ``currency``, the Instrument's quote currency, as exact decimal text
    price: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(String(3))
    source: Mapped[str] = mapped_column(String(20))
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime)


class PriceFailureRow(Base):
    """Why a Price Source gave no Quote for an Instrument in the last refresh that failed in every source (#37).

    Each refresh replaces all rows; an Instrument with rows has a Stale Price. ``position`` keeps the order the
    sources were tried in.
    """

    __tablename__ = "price_failures"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)


class NbpRateRow(Base):
    """The cached NBP Rate (D-1) for Transactions in ``currency`` dated ``day`` (issue #15).

    Only final rates are cached: a published table never changes.
    """

    __tablename__ = "nbp_rates"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    day: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    rate: Mapped[str] = mapped_column(String(30))
    published_on: Mapped[dt.date] = mapped_column(Date)
    table: Mapped[str] = mapped_column(String(30))


class QuoteHistoryRow(Base):
    """The days ``first_day`` to ``last_day`` whose Quotes of an Instrument were fetched from Stooq (issue #33).

    Days without trading are covered too, so they are not asked for again.
    """

    __tablename__ = "quote_history"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    first_day: Mapped[dt.date] = mapped_column(Date)
    last_day: Mapped[dt.date] = mapped_column(Date)


class NbpRateHistoryRow(Base):
    """The NBP table A mid rate of ``currency`` published on ``day`` (issue #33), for History (Stage 4)."""

    __tablename__ = "nbp_rate_history"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    day: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    rate: Mapped[str] = mapped_column(String(30))
    table: Mapped[str] = mapped_column(String(30))


class NbpHistoryRow(Base):
    """The days ``first_day`` to ``last_day`` whose NBP Rates of ``currency`` were fetched (issue #33)."""

    __tablename__ = "nbp_history"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    first_day: Mapped[dt.date] = mapped_column(Date)
    last_day: Mapped[dt.date] = mapped_column(Date)
