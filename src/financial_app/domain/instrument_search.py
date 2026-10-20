"""Instrument search by ISIN, name or symbol (issue #25, spec 4.1): the listings found and what a chosen one fills
in."""

import re
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Protocol

from financial_app.domain.instruments import ISIN_PATTERN, DistributionPolicy, InstrumentType


class InstrumentSearchError(Exception):
    """The search could not be done; the message is shown in the UI (Polish)."""


@dataclass(frozen=True)
class FoundListing:
    """One listing found, one of a Search Result's (``domain.header_search.SearchResult``): ``symbol`` is the ticker
    the search service shows, ``source_symbols`` the Source Symbols it gives (Price Source key to symbol,
    ``domain.prices``), ``currency`` its quote currency ("" when unknown), ``isin`` its ISIN ("" when unknown, as
    Yahoo returns none: only an ISIN searched for fills it) and ``asset_class`` the name of the Asset Class it
    belongs to ("" when its kind does not tell, e.g. an ETF).
    ``fund`` says it is a fund or an ETF, whose ISIN tells its domicile and name its distribution policy, and
    ``instrument_type`` its Instrument Type when the service tells it (issue #198).
    ``source`` names the search service that found it, when several are searched together."""

    name: str
    symbol: str
    market: str
    currency: str
    source_symbols: Mapping[str, str] = field(default_factory=dict)
    isin: str = ""
    asset_class: str = ""
    fund: bool = False
    source: str = ""
    instrument_type: InstrumentType | None = None

    @property
    def currency_label(self) -> str:
        """Its quote currency as shown, "waluta nieznana" when unknown."""
        return self.currency or "waluta nieznana"


class InstrumentSearch(Protocol):
    """A swappable search service (Yahoo, analizy.pl, both together); raises ``InstrumentSearchError``."""

    def search(self, query: str) -> list[FoundListing]: ...


class FoundListings(list[FoundListing]):
    """The results of several search services, with a ``notes`` line (Polish) for each one that failed."""

    def __init__(self, results: Iterable[FoundListing] = (), notes: Iterable[str] = ()) -> None:
        super().__init__(results)
        self.notes = list(notes)


class CombinedSearch:
    """Several search services, by the name shown beside their results, asked side by side; one failing leaves the
    others' results with a note, all failing is an ``InstrumentSearchError``. Any error counts as the service
    failing, as their undocumented APIs may change."""

    def __init__(self, searches: Mapping[str, InstrumentSearch]) -> None:
        self.searches = searches

    def search(self, query: str) -> FoundListings:
        with ThreadPoolExecutor(max_workers=len(self.searches)) as pool:
            pending = {name: pool.submit(search.search, query) for name, search in self.searches.items()}
        results, notes, errors = [], [], []
        for name, future in pending.items():
            try:
                results += [replace(result, source=name) for result in future.result()]
            except InstrumentSearchError as error:
                notes.append(f"{name} nie odpowiada")
                errors.append(str(error))
            except Exception as error:  # noqa: BLE001 - one broken service must not hide the others' results
                notes.append(f"{name} nie odpowiada")
                errors.append(f"Nieoczekiwany błąd wyszukiwarki {name}: {error}")
        if errors and len(errors) == len(self.searches):
            raise InstrumentSearchError(" ".join(errors))
        return FoundListings(results, notes)


@dataclass(frozen=True)
class FormFields:
    """The Instrument form's fields a search result can fill; ``source_symbols`` as in ``InstrumentDraft`` and
    ``asset_class`` the chosen Asset Class's name."""

    name: str = ""
    isin: str = ""
    quote_currency: str = ""
    market: str = ""
    source_symbols: Mapping[str, str] = field(default_factory=dict)
    asset_class: str = ""
    domicile: str = ""
    distribution_policy: DistributionPolicy | None = None
    # None until picked or told by a result; saving infers one (``infer_instrument_type``)
    instrument_type: InstrumentType | None = None


# A fund's domicile by its ISIN's country code, for the usual fund domiciles; any other leaves it to the user
DOMICILES = {
    "IE": "Irlandia",
    "LU": "Luksemburg",
    "PL": "Polska",
    "DE": "Niemcy",
    "FR": "Francja",
    "NL": "Holandia",
    "GB": "Wielka Brytania",
    "US": "Stany Zjednoczone",
    "CH": "Szwajcaria",
    "AT": "Austria",
    "BE": "Belgia",
    "LI": "Liechtenstein",
    "JE": "Jersey",
    "GG": "Guernsey",
    "SE": "Szwecja",
    "FI": "Finlandia",
    "DK": "Dania",
    "NO": "Norwegia",
    "ES": "Hiszpania",
    "IT": "Włochy",
}
# The words of a fund's name naming its share class's distribution policy
_POLICY_WORDS = (
    (re.compile(r"\b(acc|accumulating|accumulation)\b", re.IGNORECASE), DistributionPolicy.ACCUMULATING),
    (
        re.compile(r"\b(dist|distributing|distribution|dis|inc|income)\b", re.IGNORECASE),
        DistributionPolicy.DISTRIBUTING,
    ),
)


def fill_empty(fields: FormFields, result: FoundListing) -> FormFields:
    """``fields`` with the empty ones taken from ``result``; values already entered are never overwritten. A fund's
    domicile comes from the country of the form's ISIN and its distribution policy from the words of its name."""

    def pick(current: str, found: str) -> str:
        return current if current.strip() else found

    symbols = dict(fields.source_symbols)
    for source, symbol in result.source_symbols.items():
        symbols[source] = pick(symbols.get(source, ""), symbol)
    isin = pick(fields.isin, result.isin)
    domicile = DOMICILES.get(isin.strip().upper()[:2], "") if result.fund else ""
    policy = _policy_named(result.name) if result.fund else None
    return FormFields(
        name=pick(fields.name, result.name),
        isin=isin,
        quote_currency=pick(fields.quote_currency, result.currency),
        market=pick(fields.market, result.market),
        source_symbols=symbols,
        asset_class=pick(fields.asset_class, result.asset_class),
        domicile=pick(fields.domicile, domicile),
        distribution_policy=fields.distribution_policy or policy,
        instrument_type=fields.instrument_type or result.instrument_type,
    )


def _policy_named(name: str) -> DistributionPolicy | None:
    for words, policy in _POLICY_WORDS:
        if words.search(name):
            return policy
    return None


def looks_like_isin(query: str) -> bool:
    """Whether ``query`` has the shape of an ISIN, so its results can carry it."""
    return ISIN_PATTERN.fullmatch(query.strip().upper()) is not None
