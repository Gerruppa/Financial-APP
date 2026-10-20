"""The Instrument Card (issue #175): a large dialog on a Search Result or one of the user's Instruments, with its
price, chart and returns from its whole history fetched live, and "Dodaj jako instrument" or "Edytuj"."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from nicegui import run, ui
from sqlalchemy import Engine

from financial_app.domain.formatting import (
    format_date,
    format_percent,
    format_pln,
    format_quantity,
    format_unit_price,
)
from financial_app.domain.instrument_card import (
    CHART_PERIODS,
    FoundInstrument,
    chart_window,
    owned_instrument,
    price_summary,
    returns,
)
from financial_app.domain.instrument_search import FormFields, SearchResult, fill_empty
from financial_app.domain.instruments import DistributionPolicy, Instrument
from financial_app.domain.prices import SOURCE_NAMES, PriceSourceError, Quote
from financial_app.persistence.instruments import list_instruments
from financial_app.sources.nbp import NbpRates
from financial_app.sources.todays_view import todays_view
from financial_app.ui.charts import price_chart
from financial_app.ui.instruments import InstrumentsSection


class ListingHistory(Protocol):
    """The closes of a listing by its Source Symbols (``sources.instrument_card.CardHistory``)."""

    def of(self, source_symbols: Mapping[str, str], currency: str, last: date) -> list[Quote]: ...


@dataclass
class CardContext:
    """What a card needs: the database, today's NBP Rates for "Twoja pozycja", the ``history`` its closes come from
    and the Instrument dialog (``instruments``) its buttons open."""

    engine: Engine
    rates: NbpRates
    history: ListingHistory
    instruments: InstrumentsSection


@dataclass
class _Chosen:
    """The listing the card shows, and the user's Instrument it was opened on (``None`` for a Search Result)."""

    listing: SearchResult
    own: Instrument | None


def open_instrument_card(context: CardContext, subject: FoundInstrument | Instrument) -> None:
    """Open the card on a FoundInstrument (its first listing chosen) or on one of the user's Instruments."""
    if isinstance(subject, Instrument):
        listings, chosen = [_listing_of(subject)], _Chosen(_listing_of(subject), subject)
    else:
        listings, chosen = subject.listings, _Chosen(subject.listings[0], None)
    dialog = ui.dialog()
    dialog.on("hide", dialog.delete)

    def owner() -> Instrument | None:
        """The Instrument holding the chosen listing: the card's own one, or one added or found by Source Symbol."""
        return chosen.own or owned_instrument(chosen.listing, list_instruments(context.engine))

    with dialog, ui.card().classes("w-[1100px] max-w-[95vw] gap-4").mark("instrument-card"):
        with ui.row().classes("w-full items-start no-wrap"):
            ui.label(subject.name).classes("text-2xl font-bold grow")
            ui.button(icon="close", on_click=dialog.close).props('flat round aria-label="Zamknij kartę"')

        @ui.refreshable
        def heading() -> None:
            _heading(chosen.listing, listings, owner())

        @ui.refreshable
        def actions() -> None:
            holder = owner()
            with ui.row().classes("items-center gap-2"):
                if holder is None:
                    ui.button("Dodaj jako instrument", icon="add", on_click=add).props("no-caps").mark("card-add")
                else:
                    ui.label("Masz już ten instrument").classes("k-muted").mark("card-owned")
                    ui.button("Edytuj", icon="edit", on_click=lambda: edit(holder)).props("flat no-caps").mark(
                        "card-edit"
                    )

        @ui.refreshable
        def position() -> None:
            holder = owner()
            if holder is not None:
                _position(context, holder)

        def redraw() -> None:
            heading.refresh()
            actions.refresh()
            position.refresh()

        def added(instrument: Instrument) -> None:
            ui.notify(f"Dodano instrument {instrument.name}", type="positive")
            redraw()

        def add() -> None:
            context.instruments.open_dialog(None, prefill=chosen.listing, on_saved=added)

        def edit(instrument: Instrument) -> None:
            def saved(saved: Instrument) -> None:
                if chosen.own is not None:
                    chosen.own = saved
                redraw()

            context.instruments.open_dialog(instrument, on_saved=saved)

        with ui.row().classes("w-full items-start no-wrap gap-4"):
            with ui.column().classes("grow gap-1"):
                heading()
            actions()
        if len(listings) > 1:
            options = {index: _listing_label(listing) for index, listing in enumerate(listings)}

            def choose(index: int) -> None:
                chosen.listing = listings[index]
                redraw()
                prices.refresh()

            listing_select = ui.select(options, value=0, label="Notowanie", on_change=lambda e: choose(e.value))
            listing_select.classes("w-80").mark("card-listing")
        position()

        @ui.refreshable
        def prices() -> None:
            listing = chosen.listing
            area = ui.column().classes("w-full gap-4")
            with area:
                ui.spinner(size="lg").mark("card-loading")

            async def load() -> None:
                try:
                    # The sources answer over the network, so the window keeps working meanwhile
                    quotes = await run.io_bound(
                        context.history.of, listing.source_symbols, listing.currency, context.rates.today()
                    )
                except PriceSourceError as error:
                    area.clear()
                    with area:
                        ui.label(str(error)).classes("text-negative").mark("card-history-error")
                    return
                if quotes is None:  # the app is shutting down
                    return
                area.clear()
                with area:
                    _prices(listing, quotes, _distributing(listing, owner()))

            ui.timer(0, load, once=True)

        prices()
    dialog.open()


def _listing_of(instrument: Instrument) -> SearchResult:
    """One of the user's Instruments as the listing its card shows."""
    symbols = dict(instrument.source_symbols)
    return SearchResult(
        name=instrument.name,
        symbol=next(iter(symbols.values()), ""),
        market=instrument.market,
        currency=instrument.quote_currency,
        source_symbols=symbols,
        isin=instrument.isin,
        asset_class=instrument.asset_class_name,
    )


def _listing_label(listing: SearchResult) -> str:
    """A listing in the card's choice, e.g. "VUAA.L · LSE · USD"."""
    return " · ".join([listing.symbol, listing.market or "rynek nieznany", listing.currency or "waluta nieznana"])


def _details(listing: SearchResult, holder: Instrument | None) -> tuple[str, DistributionPolicy | None]:
    """The domicile and the distribution policy: the Instrument's own, else what the listing tells (``fill_empty``)."""
    if holder is not None and (holder.domicile or holder.distribution_policy):
        return holder.domicile, holder.distribution_policy
    told = fill_empty(FormFields(), listing)
    return told.domicile, told.distribution_policy


def _distributing(listing: SearchResult, holder: Instrument | None) -> bool:
    return _details(listing, holder)[1] is DistributionPolicy.DISTRIBUTING


def _heading(listing: SearchResult, listings: Sequence[SearchResult], holder: Instrument | None) -> None:
    """The ISIN (with a copy button), the symbols of every listing, the Asset Class and what else is known."""
    with ui.row().classes("items-center gap-3 text-sm"):
        if listing.isin:
            ui.label(f"ISIN: {listing.isin}").classes("font-medium").mark("card-isin")
            ui.button(icon="content_copy", on_click=lambda: ui.clipboard.write(listing.isin)).props(
                'flat round dense size=sm aria-label="Kopiuj ISIN"'
            )
        symbols = ", ".join(dict.fromkeys(item.symbol for item in listings if item.symbol))
        if symbols:
            ui.label(f"Symbol: {symbols}").classes("font-medium")
        asset_class = holder.asset_class_name if holder is not None else listing.asset_class
        if asset_class:
            ui.badge(asset_class).props("outline")
        if listing.source:
            ui.badge(listing.source).props("outline color=grey")
    domicile, policy = _details(listing, holder)
    sources = ", ".join(
        f"{SOURCE_NAMES.get(source, source)} {symbol}" for source, symbol in listing.source_symbols.items()
    )
    details = [
        listing.market,
        listing.currency or "waluta nieznana",
        f"Siedziba: {domicile}" if domicile else "",
        policy.label if policy else "",
        sources,
    ]
    ui.label(" · ".join(d for d in details if d)).classes("text-sm k-muted").mark("card-details")


def _position(context: CardContext, instrument: Instrument) -> None:
    """Twoja pozycja: the Instrument's quantity, value and result on each Account, whatever the View Scope."""
    view = todays_view(context.engine, context.rates)
    held = [p for p in view.positions if p.instrument_id == instrument.id]
    accounts = {account.id: account.name for account in view.accounts}
    price = view.pln_prices.get(instrument.id)
    with ui.column().classes("w-full gap-1").mark("card-position"):
        ui.label("Twoja pozycja").classes("text-lg font-bold")
        if not held:
            ui.label("Nie masz go teraz na żadnym koncie.").classes("k-muted")
            return
        for held_position in held:
            parts = [accounts.get(held_position.account_id, ""), f"{format_quantity(held_position.quantity)} szt."]
            if price is None:
                parts.append(f"koszt {format_pln(held_position.cost)} (bez ceny)")
            else:
                parts.append(f"wartość {format_pln(held_position.value(price))}")
                parts.append(f"wynik {format_pln(held_position.result(price), signed=True)}")
            ui.label(" · ".join(parts))


def _prices(listing: SearchResult, quotes: Sequence[Quote], distributing: bool) -> None:
    """The price panel, the chart with its periods and the returns table of ``quotes``; a note without any."""
    summary = price_summary(quotes)
    if summary is None:
        ui.label("Brak historii notowań dla tego instrumentu.").classes("k-muted").mark("card-no-history")
        return
    with ui.row().classes("w-full items-end gap-8").mark("card-price"):
        with ui.column().classes("gap-0"):
            ui.label(listing.symbol or listing.name).classes("text-sm k-muted")
            with ui.row().classes("items-baseline gap-2"):
                ui.label(format_unit_price(summary.price, summary.currency)).classes("text-2xl font-bold")
                _change(summary.day_change_percent)
            ui.label(format_date(summary.day)).classes("text-xs k-muted")
        with ui.column().classes("gap-0"):
            ui.label("YTD").classes("text-xs k-muted")
            _change(summary.ytd_percent)
        with ui.column().classes("gap-0"):
            ui.label("Min 12M").classes("text-xs k-muted")
            ui.label(format_unit_price(summary.low_12m, summary.currency)).classes("k-loss")
        with ui.column().classes("gap-0"):
            ui.label("Max 12M").classes("text-xs k-muted")
            ui.label(format_unit_price(summary.high_12m, summary.currency)).classes("k-gain")

    @ui.refreshable
    def chart(period: str) -> None:
        price_chart(chart_window(quotes, period), summary.currency)

    toggle = ui.toggle(list(CHART_PERIODS), value="Max", on_change=lambda e: chart.refresh(e.value))
    toggle.props("no-caps dense").mark("card-periods")
    chart("Max")
    _returns(quotes, distributing)


def _change(percent: Decimal | None) -> None:
    """A change in percent, green up and red down; a dash without one."""
    if percent is None:
        ui.label("—").classes("k-muted")
        return
    colour = "k-gain" if percent >= 0 else "k-loss"
    ui.label(format_percent(percent, signed=True)).classes(f"font-medium {colour}")


def _returns(quotes: Sequence[Quote], distributing: bool) -> None:
    """The returns of each of the last calendar years and of each period, a dash where the history is shorter."""
    table = returns(quotes)
    with ui.column().classes("w-full gap-2").mark("card-returns"):
        ui.label("Stopy zwrotu").classes("text-lg font-bold")
        for row in (
            {str(year): value for year, value in table.years.items()},
            {_PERIOD_LABELS[label]: value for label, value in table.periods.items()},
        ):
            with ui.grid(columns=len(row)).classes("w-full text-center gap-y-1"):
                for label in row:
                    ui.label(label).classes("text-sm k-muted")
                for value in row.values():
                    _change(value)
        note = "Z cen zamknięcia"
        if distributing:
            note += "; cenowe, bez wypłaconych dywidend"
        ui.label(note + ".").classes("text-xs k-muted")


_PERIOD_LABELS = {"1M": "1 miesiąc", "3M": "3 miesiące", "6M": "6 miesięcy", "1R": "1 rok", "3L": "3 lata"}
