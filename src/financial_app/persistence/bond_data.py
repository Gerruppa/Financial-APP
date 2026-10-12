"""The saved copy of the bond data sources (spec 3.4.1): the MF file's Bond Series, GUS CPI, the NBP reference rate,
and when each was last fetched. Each successful fetch replaces its whole copy."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from financial_app.domain.bonds import CpiReading, ReferenceRate, SeriesTerms
from financial_app.persistence.models import BondDataStatusRow, CpiRow, MfBondSeriesRow, ReferenceRateRow

# The bond data sources' keys, under which their fetches are recorded
MF, GUS, NBP_REFERENCE = "mf", "gus", "nbp_reference"


@dataclass(frozen=True)
class BondDataStatus:
    """A bond data source's last successful fetch (``None`` before the first) and, while it keeps failing, the time
    and Polish reason of the last failure."""

    succeeded_at: datetime | None
    failed_at: datetime | None
    error: str | None


def save_series_terms(engine: Engine, series: Iterable[SeriesTerms]) -> None:
    with Session(engine) as session, session.begin():
        session.execute(delete(MfBondSeriesRow))
        session.add_all(
            MfBondSeriesRow(
                series=terms.series,
                isin=terms.isin,
                sale_start=terms.sale_start,
                sale_end=terms.sale_end,
                issue_price=str(terms.issue_price),
                rollover_price=_text(terms.rollover_price),
                margin=_text(terms.margin),
                rates=_join(terms.rates),
                interest=_join(terms.interest),
            )
            for terms in series
        )


def load_series_terms(engine: Engine) -> dict[str, SeriesTerms]:
    """The saved Bond Series by name, e.g. ``EDO0536``."""
    with Session(engine) as session:
        return {
            row.series: SeriesTerms(
                series=row.series,
                isin=row.isin,
                sale_start=row.sale_start,
                sale_end=row.sale_end,
                issue_price=Decimal(row.issue_price),
                rollover_price=_decimal(row.rollover_price),
                margin=_decimal(row.margin),
                rates=_split(row.rates),
                interest=_split(row.interest),
            )
            for row in session.scalars(select(MfBondSeriesRow).order_by(MfBondSeriesRow.series))
        }


def save_cpi(engine: Engine, readings: Iterable[CpiReading]) -> None:
    with Session(engine) as session, session.begin():
        session.execute(delete(CpiRow))
        session.add_all(
            CpiRow(
                year=reading.year,
                month=reading.month,
                year_on_year=_text(reading.year_on_year),
                month_on_month=_text(reading.month_on_month),
            )
            for reading in readings
        )


def load_cpi(engine: Engine) -> list[CpiReading]:
    """The saved CPI readings, oldest first."""
    with Session(engine) as session:
        return [
            CpiReading(row.year, row.month, _decimal(row.year_on_year), _decimal(row.month_on_month))
            for row in session.scalars(select(CpiRow).order_by(CpiRow.year, CpiRow.month))
        ]


def save_reference_rates(engine: Engine, rates: Iterable[ReferenceRate]) -> None:
    with Session(engine) as session, session.begin():
        session.execute(delete(ReferenceRateRow))
        session.add_all(ReferenceRateRow(valid_from=rate.valid_from, rate=str(rate.rate)) for rate in rates)


def load_reference_rates(engine: Engine) -> list[ReferenceRate]:
    """The saved NBP reference rates, oldest first."""
    with Session(engine) as session:
        return [
            ReferenceRate(row.valid_from, Decimal(row.rate))
            for row in session.scalars(select(ReferenceRateRow).order_by(ReferenceRateRow.valid_from))
        ]


def mark_bond_data(engine: Engine, source: str, at: datetime, error: str | None) -> None:
    """Record a fetch of ``source`` at ``at``: a success clears the failure, a failure keeps the last success."""
    with Session(engine) as session, session.begin():
        row = session.get(BondDataStatusRow, source) or BondDataStatusRow(source=source)
        if error is None:
            row.succeeded_at, row.failed_at, row.error = at, None, None
        else:
            row.failed_at, row.error = at, error
        session.merge(row)


def bond_data_statuses(engine: Engine) -> dict[str, BondDataStatus]:
    """Each fetched source's status by its key."""
    with Session(engine) as session:
        return {
            row.source: BondDataStatus(row.succeeded_at, row.failed_at, row.error)
            for row in session.scalars(select(BondDataStatusRow))
        }


def _text(number: Decimal | None) -> str | None:
    return None if number is None else str(number)


def _decimal(text: str | None) -> Decimal | None:
    return None if text is None else Decimal(text)


def _join(numbers: tuple[Decimal | None, ...]) -> str:
    return ",".join("" if number is None else str(number) for number in numbers)


def _split(text: str) -> tuple[Decimal | None, ...]:
    # Every Series has at least one period, so "" is one period MF has not published, never none
    return tuple(Decimal(part) if part else None for part in text.split(","))
