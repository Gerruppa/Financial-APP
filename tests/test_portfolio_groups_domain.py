"""The Portfolio's grouping of an Account's Positions (issue #198): by Instrument Type or Asset Class, with each group's
value and share of the Account."""

from datetime import date
from decimal import Decimal

from financial_app.domain.instruments import Instrument, InstrumentType
from financial_app.domain.lots import Lot, Position
from financial_app.domain.portfolio_groups import Grouping, group_positions


def _instrument(instrument_id: int, name: str, kind: InstrumentType, class_name: str) -> Instrument:
    return Instrument(
        name,
        instrument_id,
        "PLN",
        instrument_type=kind,
        id=instrument_id,
        asset_class_name=class_name,
        fallback_order=(),
    )


def _position(instrument_id: int, cost: str) -> Position:
    lot = Lot(date(2026, 1, 2), Decimal(1), Decimal(cost), Decimal(cost))
    return Position(account_id=1, instrument_id=instrument_id, lots=(lot,))


INSTRUMENTS = {
    1: _instrument(1, "Beta ETF WIG20TR", InstrumentType.ETF, "Akcje polskie"),
    2: _instrument(2, "CD Projekt", InstrumentType.STOCK, "Akcje polskie"),
    3: _instrument(3, "Xtrackers MSCI World", InstrumentType.ETF, "Akcje zagraniczne"),
}
POSITIONS = [_position(1, "100"), _position(2, "200"), _position(3, "300")]
# PLN prices per unit; the third has none, so it counts at cost
PRICES = {1: Decimal(150), 2: Decimal(250), 3: None}


def test_without_grouping_the_positions_stay_one_group() -> None:
    [group] = group_positions(POSITIONS, INSTRUMENTS, PRICES, Grouping.NONE, Decimal(1000))

    assert group.positions == POSITIONS


def test_by_type_each_group_has_its_value_and_share_of_the_account_in_the_lists_order() -> None:
    groups = group_positions(POSITIONS, INSTRUMENTS, PRICES, Grouping.INSTRUMENT_TYPE, Decimal(1000))

    assert [(g.title, [p.instrument_id for p in g.positions], g.value, g.share) for g in groups] == [
        ("Akcja", [2], Decimal(250), Decimal(25)),
        ("ETF", [1, 3], Decimal(450), Decimal(45)),
    ]


def test_by_asset_class_by_the_class_names() -> None:
    groups = group_positions(POSITIONS, INSTRUMENTS, PRICES, Grouping.ASSET_CLASS, Decimal(0))

    assert [(g.title, g.value, g.share) for g in groups] == [
        ("Akcje polskie", Decimal(400), None),
        ("Akcje zagraniczne", Decimal(300), None),
    ]


def test_an_unknown_setting_is_no_grouping() -> None:
    assert Grouping.parse("instrument_type") is Grouping.INSTRUMENT_TYPE
    assert Grouping.parse(None) is Grouping.NONE
    assert Grouping.parse("cokolwiek") is Grouping.NONE
