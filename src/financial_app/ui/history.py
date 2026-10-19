"""History in the window (spec 6.1): its daily prices fetched in the background with the header status
"Historia: pobieranie… (n/N)" and the failures listed like "Wyceny", and its days computed once and shared by every
window on the database until a Transaction save, price refresh or fetch makes them outdated."""

import asyncio
import logging
from collections.abc import Callable

from nicegui import run, ui
from sqlalchemy import Engine

from financial_app.domain.formatting import format_count
from financial_app.domain.portfolio_history import DayValue
from financial_app.persistence.instruments import list_instruments
from financial_app.sources.portfolio_history import HistoryFetch, PortfolioHistory

_log = logging.getLogger(__name__)


class SharedHistory:
    """One database's History, shared by its windows: the running fetch, its progress and failures, and the days."""

    def __init__(self, history: PortfolioHistory) -> None:
        self.history = history
        self.fetching: asyncio.Future[HistoryFetch | None] | None = None
        self.progress = (0, 0)
        self.failures = HistoryFetch()
        self.days: list[DayValue] | None = None

    async def fetch(self) -> None:
        """Fetch the missing days in a worker thread, or join the fetch another window started."""
        if self.fetching is None:
            self.progress = (0, 0)
            self.fetching = asyncio.ensure_future(run.io_bound(self.history.fetch, self._advance))
        running = self.fetching
        try:
            # Shielded, so that closing this window never cancels the fetch another window waits for
            failures = await asyncio.shield(running)
        except Exception:  # noqa: BLE001 - a fetch that broke leaves History on what is cached
            _log.exception("Pobieranie historii nie powiodło się")
            failures = None
        finally:
            if self.fetching is running:
                self.fetching = None
        if failures is not None:
            self.failures = failures
        self.days = None

    async def values(self) -> list[DayValue] | None:
        """The days from the first Transaction to today, ``None`` when they cannot be computed."""
        try:
            self.days = await self.history.values()
        except Exception:  # noqa: BLE001 - the window must stay usable without History
            _log.exception("Wyliczenie historii nie powiodło się")
            self.days = None
        return self.days

    def invalidate(self) -> None:
        self.history.invalidate()
        self.days = None

    def _advance(self, done: int, total: int) -> None:
        self.progress = (done, total)


# Each database's History, shared by every window on it
_shared: dict[Engine, SharedHistory] = {}


def shared_history(engine: Engine, make: Callable[[], PortfolioHistory]) -> SharedHistory:
    """The History of ``engine``'s database, made by ``make`` for its first window."""
    if engine not in _shared:
        _shared[engine] = SharedHistory(make())
    return _shared[engine]


def history_status(engine: Engine, shared: SharedHistory) -> None:
    """ "Historia: pobieranie… (n/N)" during a fetch, red "Historia: n błędów" listing them after one that failed,
    nothing otherwise."""
    failures = len(shared.failures.instruments) + len(shared.failures.currencies)
    if shared.fetching is not None:
        done, total = shared.progress
        text = f"Historia: pobieranie… ({done}/{total})"
    elif failures:
        text = f"Historia: {format_count(failures, 'błąd', 'błędy', 'błędów')}"
    else:
        return
    button = ui.button(text, on_click=lambda: _history_errors_dialog(engine, shared.failures)).props("flat no-caps")
    button.props(f"color={'negative' if failures and shared.fetching is None else 'ink'}").mark("history-status")


def _history_errors_dialog(engine: Engine, failures: HistoryFetch) -> None:
    """The Instruments and currencies whose history the last fetch could not get, with the reasons."""
    names = {instrument.id: instrument.name for instrument in list_instruments(engine)}
    with ui.dialog() as dialog, ui.card().classes("min-w-96").mark("history-errors"):
        ui.label("Historia").classes("text-lg font-bold")
        if not failures.instruments and not failures.currencies:
            ui.label("Ostatnie pobieranie historii powiodło się.")
        for instrument_id, reason in failures.instruments.items():
            ui.label(names.get(instrument_id, f"Instrument {instrument_id}")).classes("font-medium")
            ui.label(reason).classes("text-sm pl-4")
        for currency, reason in failures.currencies.items():
            ui.label(f"Kursy NBP {currency}").classes("font-medium")
            ui.label(reason).classes("text-sm pl-4")
        with ui.row().classes("w-full justify-end"):
            ui.button("Zamknij", on_click=dialog.close).props("flat")
    dialog.on("hide", dialog.delete)
    dialog.open()
