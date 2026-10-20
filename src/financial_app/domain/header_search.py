"""The header search (issue #175): the user's own Instruments matching a query, the listings found grouped into one
Search Result per fund or company, and the Instrument already holding a listing."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from financial_app.domain.formatting import folded
from financial_app.domain.instrument_search import FoundListing
from financial_app.domain.instruments import Instrument

# How many of the user's own Instruments the header search lists
OWN_LIMIT = 5


@dataclass(frozen=True)
class SearchResult:
    """The listings found of one fund or company, in the order found: those of one ISIN, or of one name when the
    search gives no ISIN (Yahoo gives one only to an ISIN searched for)."""

    name: str
    isin: str
    listings: list[FoundListing] = field(default_factory=list)

    @property
    def asset_classes(self) -> list[str]:
        """Each Asset Class name its listings belong to, once; none when their kind does not tell."""
        return list(dict.fromkeys(listing.asset_class for listing in self.listings if listing.asset_class))

    @property
    def sources(self) -> list[str]:
        """Each search service that found its listings, once."""
        return list(dict.fromkeys(listing.source for listing in self.listings if listing.source))


def group_results(listings: Iterable[FoundListing]) -> list[SearchResult]:
    """``listings`` as one SearchResult per ISIN, or per name for those without one, in the order first found."""
    found: dict[str, SearchResult] = {}
    for listing in listings:
        key = listing.isin or f"name:{listing.name.casefold()}"
        if key not in found:
            found[key] = SearchResult(listing.name, listing.isin)
        found[key].listings.append(listing)
    return list(found.values())


def matching_instruments(instruments: Iterable[Instrument], query: str, limit: int = OWN_LIMIT) -> list[Instrument]:
    """The first ``limit`` of ``instruments`` whose name, ISIN or a Source Symbol contains ``query``, ignoring case and
    Polish letters; none for an empty query."""
    wanted = folded(query.strip())
    if not wanted:
        return []
    found = [instrument for instrument in instruments if any(wanted in folded(text) for text in _searched(instrument))]
    return found[:limit]


def _searched(instrument: Instrument) -> tuple[str, ...]:
    """The texts of an Instrument the header search looks in."""
    return (instrument.name, instrument.isin, *instrument.source_symbols.values())


def owned_instrument(listing: FoundListing, instruments: Sequence[Instrument]) -> Instrument | None:
    """The Instrument already holding ``listing``: one with any of its Source Symbols. The same ISIN on another
    exchange or in another currency is another listing, so another Instrument."""
    wanted = {(source, symbol.casefold()) for source, symbol in listing.source_symbols.items()}
    for instrument in instruments:
        if any((source, symbol.casefold()) in wanted for source, symbol in instrument.source_symbols.items()):
            return instrument
    return None
