"""Which Price Sources fit an Instrument and how to find its Source Symbol in each, for the price source help window
of an Instrument without a price (issue #274)."""

from dataclasses import dataclass

from financial_app.domain.instruments import Instrument, InstrumentType
from financial_app.domain.prices import ANALIZY, BANKIER, BOSSA, YAHOO


@dataclass(frozen=True)
class SourceHelp:
    """What a Price Source quotes (``why``), where its Source Symbol is found (``find``) and example symbols."""

    why: str
    find: str
    examples: tuple[str, ...]


SOURCE_HELP = {
    YAHOO: SourceHelp(
        "Akcje i ETF-y z giełd zagranicznych, kryptowaluty i metale; także GPW z końcówką .WA.",
        "Wyszukaj nazwę albo ISIN na finance.yahoo.com: symbol stoi obok nazwy, a jego końcówka to giełda.",
        ("AAPL (Nasdaq, USD)", "VWCE.DE (Xetra, EUR)", "ISAC.L (Londyn)", "PZU.WA (GPW)", "BTC-USD (bitcoin w USD)"),
    ),
    BOSSA: SourceHelp(
        "Akcje, ETF-y i obligacje z GPW, NewConnect i Catalyst, w złotych.",
        "Wpisz skrót z notowań GPW, taki jak u maklera, bez końcówki giełdy.",
        ("PZU", "CDR", "ETFBDIVPL"),
    ),
    ANALIZY: SourceHelp(
        "Fundusze inwestycyjne i PPK.",
        "Znajdź fundusz na analizy.pl: kod funduszu to ostatnia część adresu jego strony.",
        ("PZU60 (z analizy.pl/fundusze/ppk/PZU60)",),
    ),
    BANKIER: SourceHelp(
        "Fundusze inwestycyjne, gdy analizy.pl ich nie wycenia.",
        "Zwykle to ten sam kod funduszu co w analizy.pl; inny wpisz z adresu strony funduszu na bankier.pl.",
        ("PZU60",),
    ),
}

MANUAL_HELP = (
    "Cena ręczna: gdy żadne źródło nie notuje instrumentu (np. udziały, obligacje kupione poza giełdą). "
    "Wpisujesz ją sam i sam ją aktualizujesz."
)

# Markets the Bossa source quotes, as the user or a search names them
POLISH_MARKETS = frozenset({"GPW", "WSE", "NEWCONNECT", "CATALYST"})


@dataclass(frozen=True)
class SourceAdvice:
    """A Price Source for the Instrument: whether it ``fits`` its Instrument Type and market, and whether it is
    ``in_order``, i.e. in the Fallback Order of its Asset Class, which alone tries its Source Symbol."""

    source: str
    fits: bool
    in_order: bool
    help: SourceHelp


def advised_sources(instrument: Instrument) -> list[SourceAdvice]:
    """The sources that fit the Instrument, best first, then the other sources of its class's Fallback Order."""
    fitting = _fitting(instrument)
    others = [source for source in instrument.fallback_order if source not in fitting]
    return [
        SourceAdvice(source, source in fitting, source in instrument.fallback_order, SOURCE_HELP[source])
        for source in (*fitting, *others)
    ]


def _fitting(instrument: Instrument) -> tuple[str, ...]:
    kind = instrument.instrument_type
    if kind is InstrumentType.FUND:
        return (ANALIZY, BANKIER)
    if kind in (InstrumentType.CRYPTO, InstrumentType.METAL, InstrumentType.ETC):
        return (YAHOO,)
    if kind is InstrumentType.OTHER:
        return instrument.fallback_order
    return (BOSSA, YAHOO) if _polish(instrument) else (YAHOO,)


def _polish(instrument: Instrument) -> bool:
    """Listed in Poland: on a Polish market, or in złoty when no market is given."""
    market = instrument.market.strip().upper()
    return market in POLISH_MARKETS if market else instrument.quote_currency == "PLN"
