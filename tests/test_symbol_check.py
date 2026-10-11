"""The "Sprawdź" check of one Source Symbol in the Instrument dialog (issue #39, spec 4.1), on fake sources."""

from datetime import date
from decimal import Decimal

from financial_app.domain.prices import YAHOO, CurrencyMismatchError, PriceSourceError, Quote
from financial_app.sources.prices import SymbolCheck, check_symbol

AAPL = Quote(Decimal("254.63"), "USD", date(2026, 10, 9), YAHOO)


class FakeSource:
    """Answers ``quote`` with ``answer``, raising it when it is an exception, and records what it was asked and
    whether it still kept the Quotes of an earlier refresh then (like Bossa's categories)."""

    name = YAHOO

    def __init__(self, answer: Quote | Exception) -> None:
        self.answer = answer
        self.kept: str | None = "an earlier refresh"
        self.calls: list[str] = []

    def new_refresh(self) -> None:
        self.kept = None

    def quote(self, symbol: str, currency: str) -> Quote:
        self.calls.append(f"quote {symbol} {currency} keeping {self.kept}")
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_a_symbol_the_source_knows_gives_its_quote() -> None:
    assert check_symbol(FakeSource(AAPL), "AAPL", "USD") == SymbolCheck(quote=AAPL)


def test_the_check_fetches_anew_rather_than_from_an_earlier_refresh() -> None:
    source = FakeSource(AAPL)

    check_symbol(source, " AAPL ", "USD")

    assert source.calls == ["quote AAPL USD keeping None"]


def test_the_check_leaves_what_a_running_refresh_keeps_in_the_source() -> None:
    source = FakeSource(AAPL)

    check_symbol(source, "AAPL", "USD")

    assert source.kept == "an earlier refresh"


def test_a_currency_mismatch_is_a_warning_with_the_sources_own_quote() -> None:
    mismatch = CurrencyMismatchError("Yahoo podaje cenę AAPL w USD, a instrument jest notowany w PLN.", AAPL)

    check = check_symbol(FakeSource(mismatch), "AAPL", "PLN")

    assert check == SymbolCheck(quote=AAPL, warning="Yahoo podaje cenę AAPL w USD, a instrument jest notowany w PLN.")


def test_a_symbol_the_source_has_no_quote_for_is_an_error() -> None:
    check = check_symbol(FakeSource(PriceSourceError("Yahoo nie zna symbolu „NOSUCH”.")), "NOSUCH", "USD")

    assert check == SymbolCheck(error="Yahoo nie zna symbolu „NOSUCH”.")


def test_a_broken_source_is_an_error_too() -> None:
    check = check_symbol(FakeSource(KeyError("chart")), "AAPL", "USD")

    assert check == SymbolCheck(error="Nieoczekiwany błąd źródła: 'chart'")


def test_without_a_quote_currency_the_source_is_not_asked() -> None:
    source = FakeSource(AAPL)

    assert check_symbol(source, "AAPL", " ") == SymbolCheck(error="Wpisz walutę notowania, aby sprawdzić symbol.")
    assert source.calls == []


def test_an_empty_symbol_is_not_asked_for() -> None:
    source = FakeSource(AAPL)

    assert check_symbol(source, "  ", "USD") == SymbolCheck(error="Wpisz symbol, aby go sprawdzić.")
    assert source.calls == []
