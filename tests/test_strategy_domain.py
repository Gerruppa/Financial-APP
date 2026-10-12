"""Investment Strategies (issue #76, spec 5): Allocation Targets with tolerance bands, Instrument Targets and the
Planned Deposit split without selling."""

from decimal import Decimal

import pytest

from financial_app.domain.instruments import AssetClass, Instrument
from financial_app.domain.strategy import (
    BandStatus,
    ClassTarget,
    Strategy,
    StrategyError,
    deposit_accounts,
    strategy_view,
)

CASH, STOCKS, BONDS, GOLD = 1, 3, 4, 8
CLASSES = [
    AssetClass(CASH, "Gotówka", ()),
    AssetClass(STOCKS, "Akcje zagraniczne", ()),
    AssetClass(BONDS, "Obligacje skarbowe polskie", ()),
    AssetClass(GOLD, "Metale i surowce", ()),
]
CSPX, ACWI, EDO = 10, 11, 12


def _instrument(instrument_id: int, name: str, class_id: int) -> Instrument:
    class_name = next(c.name for c in CLASSES if c.id == class_id)
    return Instrument(name, class_id, "PLN", id=instrument_id, asset_class_name=class_name, fallback_order=())


INSTRUMENTS = {
    CSPX: _instrument(CSPX, "CSPX", STOCKS),
    ACWI: _instrument(ACWI, "ACWI", STOCKS),
    EDO: _instrument(EDO, "EDO", BONDS),
}


def _strategy(
    targets: dict[int, int | str], bands: dict[int, int] | None = None, instruments: dict[int, int] | None = None
) -> Strategy:
    return Strategy(
        None,
        {
            class_id: ClassTarget(Decimal(percent), Decimal((bands or {}).get(class_id, 5)))
            for class_id, percent in targets.items()
        },
        {instrument_id: Decimal(percent) for instrument_id, percent in (instruments or {}).items()},
    )


def _row(view, name: str):  # type: ignore[no-untyped-def]
    return next(row for row in view.rows if row.asset_class == name)


def test_each_class_shows_its_share_target_difference_and_shift_to_target() -> None:
    view = strategy_view(
        _strategy({STOCKS: 60, BONDS: 40}),
        CLASSES,
        INSTRUMENTS,
        {"Akcje zagraniczne": Decimal(7000), "Obligacje skarbowe polskie": Decimal(3000)},
        {},
    )
    stocks = _row(view, "Akcje zagraniczne")
    assert stocks.value == Decimal(7000)
    assert stocks.share == Decimal("0.7")
    assert stocks.target == ClassTarget(Decimal(60), Decimal(5))
    assert stocks.difference == Decimal(10)
    assert stocks.to_target == Decimal(-1000)
    bonds = _row(view, "Obligacje skarbowe polskie")
    assert bonds.difference == Decimal(-10)
    assert bonds.to_target == Decimal(1000)
    assert [row.asset_class for row in view.rows] == ["Akcje zagraniczne", "Obligacje skarbowe polskie"]


def test_a_class_is_green_within_its_band_yellow_up_to_twice_it_and_red_beyond() -> None:
    view = strategy_view(
        _strategy({STOCKS: 50, BONDS: 30, GOLD: 20}, bands={STOCKS: 5, BONDS: 5, GOLD: 1}),
        CLASSES,
        INSTRUMENTS,
        {
            "Akcje zagraniczne": Decimal(5500),
            "Obligacje skarbowe polskie": Decimal(2200),
            "Metale i surowce": Decimal(2300),
        },
        {},
    )
    assert _row(view, "Akcje zagraniczne").status is BandStatus.GREEN  # +5 pp, on the band's edge
    assert _row(view, "Obligacje skarbowe polskie").status is BandStatus.YELLOW  # -8 pp
    assert _row(view, "Metale i surowce").status is BandStatus.RED  # +3 pp, over twice its 1 pp band


BALANCED = {
    "Akcje zagraniczne": Decimal(6000),
    "Obligacje skarbowe polskie": Decimal(3000),
    "Metale i surowce": Decimal(1000),
}


def _deposits(view) -> dict[str, Decimal]:  # type: ignore[no-untyped-def]
    return {row.asset_class: row.from_deposit for row in view.rows}


def test_a_planned_deposit_fills_the_most_under_target_class_first() -> None:
    view = strategy_view(
        _strategy({STOCKS: 50, BONDS: 30, GOLD: 20}), CLASSES, INSTRUMENTS, BALANCED, {}, Decimal(1000)
    )
    assert _deposits(view) == {
        "Akcje zagraniczne": Decimal(0),
        "Obligacje skarbowe polskie": Decimal(0),
        "Metale i surowce": Decimal(1000),
    }


def test_a_larger_planned_deposit_raises_the_under_target_classes_together() -> None:
    view = strategy_view(
        _strategy({STOCKS: 50, BONDS: 30, GOLD: 20}), CLASSES, INSTRUMENTS, BALANCED, {}, Decimal(2500)
    )
    assert _deposits(view) == {
        "Akcje zagraniczne": Decimal(250),
        "Obligacje skarbowe polskie": Decimal(750),
        "Metale i surowce": Decimal(1500),
    }


def test_the_deposit_needed_for_full_rebalancing_brings_every_class_to_its_target_without_selling() -> None:
    view = strategy_view(_strategy({STOCKS: 50, BONDS: 30, GOLD: 20}), CLASSES, INSTRUMENTS, BALANCED, {})
    assert view.rebalancing_deposit == Decimal(2000)


def test_full_rebalancing_without_selling_is_impossible_while_a_class_without_a_target_holds_value() -> None:
    view = strategy_view(_strategy({STOCKS: 50, BONDS: 50}), CLASSES, INSTRUMENTS, BALANCED, {})
    assert view.rebalancing_deposit is None
    assert _row(view, "Metale i surowce").from_deposit == Decimal(0)


STOCKS_ONLY = {"Akcje zagraniczne": Decimal(6000)}
STOCK_HOLDINGS = {"Akcje zagraniczne": {CSPX: Decimal(4000), ACWI: Decimal(2000)}}


def _instrument_deposits(view, name: str) -> dict[str, Decimal | None]:  # type: ignore[no-untyped-def]
    return {row.instrument.name: row.from_deposit for row in _row(view, name).instruments}


def test_a_class_splits_its_part_of_the_deposit_toward_its_instrument_targets() -> None:
    strategy = _strategy({STOCKS: 100}, instruments={CSPX: 50, ACWI: 50})
    view = strategy_view(strategy, CLASSES, INSTRUMENTS, STOCKS_ONLY, STOCK_HOLDINGS, Decimal(2000))
    assert _instrument_deposits(view, "Akcje zagraniczne") == {"CSPX": Decimal(0), "ACWI": Decimal(2000)}
    acwi = next(row for row in _row(view, "Akcje zagraniczne").instruments if row.instrument.id == ACWI)
    assert (acwi.value, acwi.share, acwi.target) == (Decimal(2000), Decimal(2000) / Decimal(6000), Decimal(50))


def test_an_instrument_target_may_name_an_instrument_not_held_yet() -> None:
    strategy = _strategy({STOCKS: 100}, instruments={CSPX: 60, ACWI: 40})
    view = strategy_view(strategy, CLASSES, INSTRUMENTS, STOCKS_ONLY, {"Akcje zagraniczne": {CSPX: Decimal(6000)}})
    assert [(row.instrument.name, row.value) for row in _row(view, "Akcje zagraniczne").instruments] == [
        ("CSPX", Decimal(6000)),
        ("ACWI", Decimal(0)),
    ]


def test_a_class_without_instrument_targets_splits_its_part_in_proportion_to_its_holdings() -> None:
    view = strategy_view(_strategy({STOCKS: 100}), CLASSES, INSTRUMENTS, STOCKS_ONLY, STOCK_HOLDINGS, Decimal(1500))
    assert _instrument_deposits(view, "Akcje zagraniczne") == {"CSPX": Decimal(1000), "ACWI": Decimal(500)}


def test_instrument_targets_not_summing_to_100_percent_block_the_class_split() -> None:
    strategy = _strategy({STOCKS: 100}, instruments={CSPX: 50, ACWI: 30})
    view = strategy_view(strategy, CLASSES, INSTRUMENTS, STOCKS_ONLY, STOCK_HOLDINGS, Decimal(1500))
    stocks = _row(view, "Akcje zagraniczne")
    assert stocks.instrument_targets_sum == Decimal(80)
    assert stocks.split_blocked
    assert stocks.from_deposit == Decimal(1500)
    assert _instrument_deposits(view, "Akcje zagraniczne") == {"CSPX": None, "ACWI": None}


@pytest.mark.parametrize(
    ("percent", "band", "instrument", "message"),
    [
        (101, 5, 50, "Cel klasy.*od 0 do 100"),
        (-1, 5, 50, "Cel klasy.*od 0 do 100"),
        (50, -1, 50, "Pasmo tolerancji.*od 0 do 100"),
        (50, 5, 120, "Cel w klasie.*od 0 do 100"),
    ],
)
def test_targets_and_bands_must_lie_between_0_and_100(percent: int, band: int, instrument: int, message: str) -> None:
    with pytest.raises(StrategyError, match=message):
        _strategy({STOCKS: percent}, bands={STOCKS: band}, instruments={CSPX: instrument})


def test_targets_that_do_not_sum_to_100_percent_are_reported_not_refused() -> None:
    view = strategy_view(_strategy({STOCKS: 50, BONDS: 30}), CLASSES, INSTRUMENTS, BALANCED, {})
    assert view.targets_sum == Decimal(80)
    assert strategy_view(None, CLASSES, INSTRUMENTS, BALANCED, {}).targets_sum is None


IKE, XTB, BANK = 1, 2, 3


def test_in_total_each_class_to_buy_suggests_the_accounts_whose_strategy_or_holdings_include_it() -> None:
    view = strategy_view(
        _strategy({STOCKS: 50, BONDS: 30, GOLD: 20}), CLASSES, INSTRUMENTS, BALANCED, {}, Decimal(2500)
    )
    accounts = deposit_accounts(
        view,
        CLASSES,
        {IKE: Strategy(IKE, {STOCKS: ClassTarget(Decimal(100))})},
        {
            IKE: {"Akcje zagraniczne": Decimal(6000)},
            XTB: {"Akcje zagraniczne": Decimal(100), "Metale i surowce": Decimal(1000)},
            BANK: {"Obligacje skarbowe polskie": Decimal(3000)},
        },
    )
    assert accounts == {
        "Akcje zagraniczne": (IKE, XTB),
        "Obligacje skarbowe polskie": (BANK,),
        "Metale i surowce": (XTB,),
    }


def test_a_split_multi_asset_fund_counts_in_the_class_but_takes_none_of_its_deposit() -> None:
    vanguard = Instrument(
        "Vanguard",
        GOLD,
        "PLN",
        multi_asset_split={STOCKS: Decimal(50), GOLD: Decimal(50)},
        id=20,
        asset_class_name="Metale i surowce",
        fallback_order=(),
        split_class_names={STOCKS: "Akcje zagraniczne", GOLD: "Metale i surowce"},
    )
    holdings = {"Akcje zagraniczne": {CSPX: Decimal(4000), 20: Decimal(2000)}}
    view = strategy_view(
        _strategy({STOCKS: 100}), CLASSES, INSTRUMENTS | {20: vanguard}, STOCKS_ONLY, holdings, Decimal(1500)
    )
    stocks = _row(view, "Akcje zagraniczne")
    assert stocks.value == Decimal(6000)
    assert [(row.instrument.name, row.from_deposit) for row in stocks.instruments] == [("CSPX", Decimal(1500))]
