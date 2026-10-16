"""Reading and saving Benchmarks (issue #91), and seeding the sheet's defaults once."""

from decimal import Decimal

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from financial_app.domain.benchmarks import DEFAULT_BENCHMARKS, Benchmark, BenchmarkError, BenchmarkKind
from financial_app.domain.instruments import InstrumentDraft
from financial_app.domain.prices import STOOQ, YAHOO
from financial_app.persistence.instruments import add_instrument, list_asset_classes, list_instruments
from financial_app.persistence.models import BenchmarkRow
from financial_app.persistence.settings import BENCHMARKS_SEEDED, load_setting, save_setting

# The class a default benchmark Instrument goes to when its own was renamed or deleted
FALLBACK_CLASS = "Inne"


def list_benchmarks(engine: Engine) -> list[Benchmark]:
    """Every Benchmark in the order they were added."""
    with Session(engine) as session:
        rows = session.scalars(select(BenchmarkRow).order_by(BenchmarkRow.position))
        return [_to_benchmark(row) for row in rows]


def add_benchmark(engine: Engine, benchmark: Benchmark) -> Benchmark:
    """Add ``benchmark`` at the end of the list; one comparing against the same thing with the same offset is
    refused."""
    if any(benchmark.same_as(other) for other in list_benchmarks(engine)):
        raise BenchmarkError("Taki benchmark już jest na liście.")
    with Session(engine) as session, session.begin():
        position = session.scalar(select(func.max(BenchmarkRow.position))) or 0
        row = BenchmarkRow(
            kind=benchmark.kind.value,
            instrument_id=benchmark.instrument_id,
            account_id=benchmark.account_id,
            offset=str(benchmark.offset),
            shown=benchmark.shown,
            position=position + 1,
        )
        session.add(row)
        session.flush()
        return _to_benchmark(row)


def set_shown(engine: Engine, benchmark_id: int, shown: bool) -> None:
    """Show the benchmark on the chart or hide it."""
    with Session(engine) as session, session.begin():
        row = session.get(BenchmarkRow, benchmark_id)
        if row is not None:
            row.shown = shown


def delete_benchmark(engine: Engine, benchmark_id: int) -> None:
    with Session(engine) as session, session.begin():
        session.execute(delete(BenchmarkRow).where(BenchmarkRow.id == benchmark_id))


def ensure_default_benchmarks(engine: Engine) -> bool:
    """The first time, add the sheet's defaults: CPI and the ``DEFAULT_BENCHMARKS`` Instruments, each found in the
    catalog by its Yahoo or Stooq symbol or its name, else created there. Returns whether it added them now; once
    done (clearing the data undoes it), the user's list stays as they left it."""
    if load_setting(engine, BENCHMARKS_SEEDED):
        return False
    instruments = list_instruments(engine)
    classes = {asset_class.name: asset_class.id for asset_class in list_asset_classes(engine)}
    benchmarks = [Benchmark(BenchmarkKind.CPI)]
    for default in DEFAULT_BENCHMARKS:
        symbols = {source: symbol for source, symbol in ((YAHOO, default.yahoo), (STOOQ, default.stooq)) if symbol}
        found = next(
            (
                instrument
                for instrument in instruments
                if instrument.name.casefold() == default.name.casefold()
                or any(
                    instrument.source_symbols.get(source, "").casefold() == symbol.casefold()
                    for source, symbol in symbols.items()
                )
            ),
            None,
        )
        if found is None:
            class_id = classes.get(default.asset_class, classes.get(FALLBACK_CLASS))
            if class_id is None:
                continue
            market = default.name.partition(":")[0]
            found = add_instrument(
                engine, InstrumentDraft(default.name, class_id, default.currency, market, source_symbols=symbols)
            )
        benchmarks.append(Benchmark(BenchmarkKind.INSTRUMENT, instrument_id=found.id))
    existing = list_benchmarks(engine)
    for benchmark in benchmarks:
        if not any(benchmark.same_as(other) for other in existing):
            add_benchmark(engine, benchmark)
    save_setting(engine, BENCHMARKS_SEEDED, "1")
    return True


def _to_benchmark(row: BenchmarkRow) -> Benchmark:
    return Benchmark(
        BenchmarkKind(row.kind), row.instrument_id, row.account_id, Decimal(row.offset), row.shown, id=row.id
    )
