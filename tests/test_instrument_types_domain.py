"""Instrument Type (issue #198): the fixed list and the Type a new Instrument gets from what is known about it."""

from decimal import Decimal

import pytest

from financial_app.domain.instruments import (
    InstrumentDraft,
    InstrumentType,
    by_type,
    infer_instrument_type,
    instrument_matches,
)
from financial_app.domain.prices import ANALIZY, BOSSA, YAHOO


def test_the_list_is_fixed_and_labelled_in_polish() -> None:
    assert [kind.label for kind in InstrumentType] == [
        "Akcja",
        "ETF",
        "ETC",
        "Fundusz",
        "Obligacja skarbowa",
        "Obligacja",
        "Kryptowaluta",
        "Metal fizyczny",
        "Inne",
    ]


@pytest.mark.parametrize(
    ("name", "asset_class", "grams", "symbols", "found", "expected"),
    [
        ("EDO0136", "Obligacje skarbowe polskie", None, {}, None, InstrumentType.TREASURY_BOND),
        ("Krugerrand 1 oz", "Metale i surowce", Decimal("31.1034768"), {}, None, InstrumentType.METAL),
        ("iShares MSCI World", "Akcje zagraniczne", None, {YAHOO: "IWDA.AS"}, InstrumentType.ETF, InstrumentType.ETF),
        ("PZU Akcji", "Akcje polskie", None, {ANALIZY: "PZU60"}, None, InstrumentType.FUND),
        ("Bitcoin", "Kryptowaluty", None, {YAHOO: "BTC-USD"}, None, InstrumentType.CRYPTO),
        ("PZU", "Akcje polskie", None, {BOSSA: "PZU"}, None, InstrumentType.OTHER),
        # A Series' name outside the treasury bond class is no Series
        ("EDO0136", "Inne", None, {}, None, InstrumentType.OTHER),
    ],
)
def test_a_new_instrument_takes_its_type_from_what_is_known(
    name: str,
    asset_class: str,
    grams: Decimal | None,
    symbols: dict[str, str],
    found: InstrumentType | None,
    expected: InstrumentType,
) -> None:
    assert infer_instrument_type(name, asset_class, grams, symbols, found) is expected


def test_a_series_or_a_metal_weight_outweighs_what_a_search_said() -> None:
    assert (
        infer_instrument_type("Złota moneta", "Metale i surowce", Decimal(31), {}, InstrumentType.FUND)
        is InstrumentType.METAL
    )


def _draft(name: str, kind: InstrumentType, **fields: object) -> InstrumentDraft:
    return InstrumentDraft(name, 1, "PLN", instrument_type=kind, **fields)  # type: ignore[arg-type]


def test_instruments_are_grouped_by_type_in_the_lists_order_and_by_name() -> None:
    groups = by_type(
        [
            _draft("Xtrackers", InstrumentType.ETF),
            _draft("Bitcoin", InstrumentType.CRYPTO),
            _draft("amundi", InstrumentType.ETF),
        ]
    )

    assert [(kind, [i.name for i in group]) for kind, group in groups] == [
        (InstrumentType.ETF, ["amundi", "Xtrackers"]),
        (InstrumentType.CRYPTO, ["Bitcoin"]),
    ]


@pytest.mark.parametrize(
    ("query", "matches"), [("", True), ("zloto", True), ("ie00b4nd", True), ("gld", True), ("x", False)]
)
def test_the_search_looks_at_the_name_isin_and_source_symbols(query: str, matches: bool) -> None:
    gold = _draft("Złoto fizyczne", InstrumentType.ETC, isin="IE00B4ND3602", source_symbols={YAHOO: "GLD"})

    assert instrument_matches(gold, query) is matches
