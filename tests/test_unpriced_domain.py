"""The "Instrumenty bez wyceny" list: held Instruments without an automatic price, with the reason (issue #40)."""

from collections.abc import Mapping

from financial_app.domain.instruments import Instrument
from financial_app.domain.prices import BOSSA, YAHOO, default_fallback_order
from financial_app.domain.valuation import Unpriced, UnpricedReason, instruments_without_price

AKCJE_POLSKIE = "Akcje polskie"


def _instrument(
    id: int,
    symbols: Mapping[str, str] | None = None,
    asset_class_name: str = AKCJE_POLSKIE,
    fallback_order: tuple[str, ...] | None = None,
    name: str | None = None,
) -> Instrument:
    if fallback_order is None:
        fallback_order = default_fallback_order(asset_class_name)
    return Instrument(
        name or f"I{id}",
        2,
        "PLN",
        "GPW",
        None,
        dict(symbols or {}),
        id=id,
        asset_class_name=asset_class_name,
        fallback_order=fallback_order,
    )


def test_a_held_instrument_without_a_source_symbol_has_no_source() -> None:
    instrument = _instrument(1)

    assert instruments_without_price([instrument], {1}, set(), {}) == [Unpriced(instrument, UnpricedReason.NO_SOURCE)]


def test_a_symbol_for_a_source_its_asset_class_left_out_counts_as_no_source() -> None:
    # The user removed Yahoo from the class's Fallback Order (issue #41)
    instrument = _instrument(1, {YAHOO: "PZU.WA"}, fallback_order=(BOSSA,))

    assert instruments_without_price([instrument], {1}, set(), {}) == [Unpriced(instrument, UnpricedReason.NO_SOURCE)]


def test_a_symbol_outside_the_classs_fallback_order_counts_as_no_source() -> None:
    # Akcje polskie are tried in Bossa and Yahoo only
    instrument = _instrument(1, {"analizy": "PZU60"})

    assert instruments_without_price([instrument], {1}, set(), {}) == [Unpriced(instrument, UnpricedReason.NO_SOURCE)]


def test_a_held_instrument_failing_in_every_source_carries_the_reasons() -> None:
    instrument = _instrument(1, {"yahoo": "XXX.WA"})
    reasons = {"yahoo": "Yahoo nie zna symbolu „XXX.WA”."}

    # Also with an older Quote: the latest refresh failed, so the Instrument has no automatic price
    assert instruments_without_price([instrument], {1}, {1}, {1: reasons}) == [
        Unpriced(instrument, UnpricedReason.FAILED, reasons)
    ]


def test_a_symbol_not_refreshed_yet_waits_for_the_refresh() -> None:
    instrument = _instrument(1, {"yahoo": "PZU.WA"})

    assert instruments_without_price([instrument], {1}, set(), {}) == [
        Unpriced(instrument, UnpricedReason.NOT_REFRESHED)
    ]


def test_a_removed_symbol_counts_as_no_source_despite_an_old_failure() -> None:
    instrument = _instrument(1)

    assert instruments_without_price([instrument], {1}, set(), {1: {"yahoo": "błąd"}}) == [
        Unpriced(instrument, UnpricedReason.NO_SOURCE)
    ]


def test_unheld_quoted_and_bond_series_instruments_are_not_listed() -> None:
    unheld = _instrument(1)
    quoted = _instrument(2, {"yahoo": "PZU.WA"})
    bond = _instrument(3, asset_class_name="Obligacje skarbowe polskie", name="EDO0836")

    assert instruments_without_price([unheld, quoted, bond], {2, 3}, {2}, {}) == []


def test_a_treasury_bond_on_catalyst_without_a_bossa_symbol_is_listed() -> None:
    bond = _instrument(1, asset_class_name="Obligacje skarbowe polskie", name="DS1030")

    assert instruments_without_price([bond], {1}, set(), {}) == [Unpriced(bond, UnpricedReason.NO_SOURCE)]


def test_the_list_keeps_the_instruments_order() -> None:
    first, second = _instrument(2), _instrument(1)

    listed = instruments_without_price([first, second], {1, 2}, set(), {})

    assert [item.instrument for item in listed] == [first, second]


def test_a_fund_code_prices_through_bankier_in_a_class_with_only_bankier() -> None:
    instrument = _instrument(1, {"analizy": "PZU60"}, fallback_order=("bankier",))

    assert instruments_without_price([instrument], {1}, set(), {}) == [
        Unpriced(instrument, UnpricedReason.NOT_REFRESHED)
    ]
