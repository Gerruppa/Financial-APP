"""ORM models. The schema itself is created and evolved only by Alembic migrations."""

import datetime as dt
from enum import Enum
from typing import ClassVar

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


class OnClear(Enum):
    """Whether clearing the portfolio (Ustawienia > Wyczyść dane) removes a model's rows; every model declares it."""

    DELETE = "delete"
    KEEP = "keep"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    on_clear: ClassVar[OnClear]


class AppSetting(Base):
    """A key/value application setting (e.g. the last View Scope)."""

    on_clear = OnClear.KEEP
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class AccountRow(Base):
    """An Account (spec 3.1). The ``Row`` suffix keeps it apart from ``domain.accounts.Account``, its in-memory form."""

    on_clear = OnClear.DELETE
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

    on_clear = OnClear.DELETE
    __tablename__ = "account_cash_currencies"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)


class TransactionRow(Base):
    """A Transaction (spec 3.3); ``domain.transactions.Transaction`` is its in-memory form.

    The Tax Amount is not stored: it follows from the stored NBP Rate.
    """

    on_clear = OnClear.DELETE
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
    # PLN, or the foreign ``cash_currency`` a trade on an Account without PLN is paid from (issue #124)
    commission_currency: Mapped[str] = mapped_column(String(3), server_default="PLN")
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
    # Dividend and DRIP only: the gross amount and the withholding tax, in the Dividend's currency (issue #18); an
    # Early Redemption (a Sell) has the tax withheld from it too, in PLN (L-5)
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
    # A Sell only: the Transaction that opened the Lot it takes its units from, instead of FIFO (L-5, ADR-0007)
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"))
    # Reconciliation (L-17, spec 7): the broker's external id of the Transaction it was paired with, and the day the
    # user resolved it; a reconciled Transaction is not offered for pairing again
    broker_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    reconciled_on: Mapped[dt.date | None] = mapped_column(Date)
    # A confirmed Recurring Rule Draft (issue #97): the rule and the occurrence it covers; deleting the rule unlinks it
    recurring_rule_id: Mapped[int | None] = mapped_column(ForeignKey("recurring_rules.id", ondelete="SET NULL"))
    recurring_occurrence: Mapped[dt.date | None] = mapped_column(Date)


class SkippedBrokerRow(Base):
    """A broker's Transaction the user chose not to add in a Reconciliation (L-17), so it is not offered again."""

    on_clear = OnClear.DELETE
    __tablename__ = "skipped_broker_rows"

    external_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    skipped_on: Mapped[dt.date] = mapped_column(Date)


class AssetClassRow(Base):
    """An Asset Class (spec 3.2); ``position`` keeps the sheet's order, with classes the user adds at the end.
    ``fallback_order`` is its Fallback Order (spec 4.1): the Price Source keys, comma-separated, empty for none."""

    on_clear = OnClear.DELETE
    __tablename__ = "asset_classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100, collation="NOCASE"), unique=True)
    position: Mapped[int] = mapped_column(Integer)
    fallback_order: Mapped[str] = mapped_column(String(100), server_default="")
    # The class whose Instruments get a Multi-asset Split (issue #75), so a rename keeps it
    multi_asset: Mapped[bool] = mapped_column(Boolean, server_default=false())


class InstrumentRow(Base):
    """An Instrument (spec 3.2); ``domain.instruments.Instrument`` is its in-memory form."""

    on_clear = OnClear.DELETE
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200, collation="NOCASE"), unique=True)
    asset_class_id: Mapped[int] = mapped_column(ForeignKey("asset_classes.id"), index=True)
    quote_currency: Mapped[str] = mapped_column(String(3))
    market: Mapped[str] = mapped_column(String(100))
    # In the quote currency, as exact decimal text like the FX Conversion Fee
    manual_price: Mapped[str | None] = mapped_column(String(30))
    # A physical metal's weight per unit and Buyback Spread % (issue #34), also exact decimal text
    metal_grams: Mapped[str | None] = mapped_column(String(30))
    buyback_spread_percent: Mapped[str | None] = mapped_column(String(20))
    # Optional and not unique: each listing of a security is its own Instrument (issue #25)
    isin: Mapped[str] = mapped_column(String(12), default="", server_default="")
    # A fund's details entered by the user (issue #42); the TER is exact decimal text, the policy a DistributionPolicy
    ter_percent: Mapped[str | None] = mapped_column(String(20))
    distribution_policy: Mapped[str | None] = mapped_column(String(20))
    domicile: Mapped[str] = mapped_column(String(100), default="", server_default="")
    # The decimal places a quantity may have, which round the quantity proposed from an amount (#120)
    quantity_decimals: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    asset_class: Mapped[AssetClassRow] = relationship()
    source_symbols: Mapped[list[SourceSymbolRow]] = relationship(cascade="all, delete-orphan")
    multi_asset_split: Mapped[list[MultiAssetShareRow]] = relationship(cascade="all, delete-orphan")
    rate_correction: Mapped[RateCorrectionRow | None] = relationship(cascade="all, delete-orphan")


class SourceSymbolRow(Base):
    """An Instrument's Source Symbol in one Price Source (issue #30); ``source`` is a ``domain.prices`` key."""

    on_clear = OnClear.DELETE
    __tablename__ = "source_symbols"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(100))


class RateCorrectionRow(Base):
    """The user's corrections of a Bond Series' MF rates (spec 3.4.1): exact decimal text, ``rates`` one per period,
    comma-separated, empty where the MF file's rate stands."""

    on_clear = OnClear.DELETE
    __tablename__ = "bond_rate_corrections"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    margin: Mapped[str | None] = mapped_column(String(20))
    rates: Mapped[str] = mapped_column(Text, default="", server_default="")


class MultiAssetShareRow(Base):
    """One Asset Class's share of an Instrument's Multi-asset Split (issue #75); an Instrument's rows sum to 100."""

    on_clear = OnClear.DELETE
    __tablename__ = "multi_asset_shares"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    asset_class_id: Mapped[int] = mapped_column(ForeignKey("asset_classes.id"), primary_key=True, index=True)
    # Percent, as exact decimal text
    percent: Mapped[str] = mapped_column(String(20))

    asset_class: Mapped[AssetClassRow] = relationship()


class StrategyRow(Base):
    """An Investment Strategy (issue #76): Total's when ``account_id`` is empty, else that Account's own. The
    repository keeps one per Account and one for Total (SQLite lets a unique column hold several NULLs)."""

    on_clear = OnClear.DELETE
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), unique=True)

    class_targets: Mapped[list[ClassTargetRow]] = relationship(cascade="all, delete-orphan")
    instrument_targets: Mapped[list[InstrumentTargetRow]] = relationship(cascade="all, delete-orphan")


class ClassTargetRow(Base):
    """An Allocation Target of a strategy with its tolerance band (± percentage points)."""

    on_clear = OnClear.DELETE
    __tablename__ = "class_targets"

    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), primary_key=True)
    asset_class_id: Mapped[int] = mapped_column(ForeignKey("asset_classes.id"), primary_key=True, index=True)
    # Percent and percentage points, as exact decimal text
    percent: Mapped[str] = mapped_column(String(20))
    band: Mapped[str] = mapped_column(String(20))


class InstrumentTargetRow(Base):
    """An Instrument Target of a strategy: percent of the Instrument's Asset Class."""

    on_clear = OnClear.DELETE
    __tablename__ = "instrument_targets"

    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True, index=True)
    percent: Mapped[str] = mapped_column(String(20))


class QuoteRow(Base):
    """An Instrument's Quote for ``day`` (issue #30); a later fetch on the same day replaces it."""

    on_clear = OnClear.DELETE
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

    on_clear = OnClear.DELETE
    __tablename__ = "price_failures"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)


class NbpRateRow(Base):
    """The cached NBP Rate (D-1) for Transactions in ``currency`` dated ``day`` (issue #15).

    Only final rates are cached: a published table never changes.
    """

    on_clear = OnClear.KEEP
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

    on_clear = OnClear.DELETE
    __tablename__ = "quote_history"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    first_day: Mapped[dt.date] = mapped_column(Date)
    last_day: Mapped[dt.date] = mapped_column(Date)


class NbpRateHistoryRow(Base):
    """The NBP table A mid rate of ``currency`` published on ``day`` (issue #33), for History (Stage 4)."""

    on_clear = OnClear.KEEP
    __tablename__ = "nbp_rate_history"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    day: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    rate: Mapped[str] = mapped_column(String(30))
    table: Mapped[str] = mapped_column(String(30))


class NbpHistoryRow(Base):
    """The days ``first_day`` to ``last_day`` whose NBP Rates of ``currency`` were fetched (issue #33)."""

    on_clear = OnClear.KEEP
    __tablename__ = "nbp_history"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    first_day: Mapped[dt.date] = mapped_column(Date)
    last_day: Mapped[dt.date] = mapped_column(Date)


class MfBondSeriesRow(Base):
    """A Bond Series as the MF file last fetched lists it (spec 3.4.1); each fetch replaces all rows.

    ``rates`` and ``interest`` hold one decimal per period, comma-separated, empty where MF has published none.
    """

    on_clear = OnClear.KEEP
    __tablename__ = "mf_bond_series"

    series: Mapped[str] = mapped_column(String(10), primary_key=True)
    isin: Mapped[str] = mapped_column(String(12))
    sale_start: Mapped[dt.date] = mapped_column(Date)
    sale_end: Mapped[dt.date] = mapped_column(Date)
    issue_price: Mapped[str] = mapped_column(String(20))
    rollover_price: Mapped[str | None] = mapped_column(String(20))
    margin: Mapped[str | None] = mapped_column(String(20))
    rates: Mapped[str] = mapped_column(Text)
    interest: Mapped[str] = mapped_column(Text)


class CpiRow(Base):
    """The GUS consumer price indices of a month (spec 3.4.1); each fetch replaces all rows."""

    on_clear = OnClear.KEEP
    __tablename__ = "cpi"

    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[int] = mapped_column(Integer, primary_key=True)
    year_on_year: Mapped[str | None] = mapped_column(String(20))
    month_on_month: Mapped[str | None] = mapped_column(String(20))


class ReferenceRateRow(Base):
    """The NBP reference rate in force from ``valid_from`` (spec 3.4.1); each fetch replaces all rows."""

    on_clear = OnClear.KEEP
    __tablename__ = "nbp_reference_rates"

    valid_from: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    rate: Mapped[str] = mapped_column(String(20))


class BondDataStatusRow(Base):
    """The last successful fetch of a bond data source and, while it keeps failing, the last failure's reason."""

    on_clear = OnClear.KEEP
    __tablename__ = "bond_data_status"

    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    succeeded_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    failed_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(Text)


class BenchmarkRow(Base):
    """A Benchmark (issue #91): CPI, an Instrument or an Account (``kind``), with its offset in pp a year (Decimal as
    text), whether the chart shows it, and its place in the list."""

    on_clear = OnClear.DELETE
    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    offset: Mapped[str] = mapped_column(String(20))
    shown: Mapped[bool] = mapped_column(Boolean)
    position: Mapped[int] = mapped_column(Integer)


class ContributionLimitRow(Base):
    """A Contribution Limit (issue #95): one per year and limited Account Type, its PLN amount (Decimal as text) or
    ``None`` while the year's row has none entered."""

    on_clear = OnClear.KEEP
    __tablename__ = "contribution_limits"

    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    amount: Mapped[str | None] = mapped_column(String(20))


class ValuationSnapshotRow(Base):
    """A Valuation Snapshot of one View Scope (issue #115, ADR-0008): Total (``account_id`` ``None``) or an Account,
    at most one a calendar day (``taken_on``), its value and Net Deposits in PLN (Decimals as text)."""

    on_clear = OnClear.DELETE
    __tablename__ = "valuation_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    taken_on: Mapped[dt.date] = mapped_column(Date, index=True)
    taken_at: Mapped[dt.datetime] = mapped_column(DateTime)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    value: Mapped[str] = mapped_column(String(30))
    net_deposits: Mapped[str] = mapped_column(String(30))


class InvestmentGoalRow(Base):
    """The Investment Goal of one View Scope (issue #96): Total (``account_id`` ``None``) or an Account, the amount
    or the FIRE expenses and withdrawal rate (``mode``), the optional target date and the forecast's assumptions
    (Decimals as text; ``monthly_deposit`` ``None`` for the scope's average)."""

    on_clear = OnClear.DELETE
    __tablename__ = "investment_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(20))
    amount: Mapped[str | None] = mapped_column(String(30))
    yearly_expenses: Mapped[str | None] = mapped_column(String(30))
    withdrawal_rate: Mapped[str] = mapped_column(String(20))
    target_date: Mapped[dt.date | None] = mapped_column(Date)
    real_return: Mapped[str] = mapped_column(String(20))
    monthly_deposit: Mapped[str | None] = mapped_column(String(30))


class RecurringRuleRow(Base):
    """A Recurring Rule (issue #97, spec 3.3.1): a Deposit or Buy of ``amount`` (Decimal as text) in ``currency``
    falling due on ``day_of_month`` every ``frequency`` from ``start_date``; ``domain.recurring.RecurringRule`` is its
    in-memory form."""

    on_clear = OnClear.DELETE
    __tablename__ = "recurring_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    transaction_type: Mapped[str] = mapped_column(String(20))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"))
    amount: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(String(3))
    frequency: Mapped[str] = mapped_column(String(20))
    day_of_month: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[dt.date] = mapped_column(Date)
    end_date: Mapped[dt.date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean)


class RecurringRuleSkipRow(Base):
    """An occurrence of a Recurring Rule the user skipped (issue #97), so it is no Draft any more."""

    on_clear = OnClear.DELETE
    __tablename__ = "recurring_rule_skips"

    rule_id: Mapped[int] = mapped_column(ForeignKey("recurring_rules.id", ondelete="CASCADE"), primary_key=True)
    occurrence_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
