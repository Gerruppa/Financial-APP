"""The calendar of the Obligacje tab (L-9, spec 3.4.1): the coupons, the anniversaries with a new rate and the
maturities of the Bond Series held, over the next 12 months."""

from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.bond_calendar import EventKind, bond_calendar
from financial_app.domain.bond_valuation import BondData, RateLabel
from financial_app.domain.bonds import BondSeries, CpiReading, SeriesTerms
from financial_app.domain.instruments import Instrument
from financial_app.domain.lots import Lot, Position

TODAY = date(2026, 10, 8)
BONDS = Account("Obligacje", "PKO BP", AccountType.BONDS, ("PLN",), id=1)
IKE = Account("IKE obligacje", "PKO BP", AccountType.IKE, ("PLN",), id=2)


def _instrument(instrument_id: int, name: str) -> Instrument:
    return Instrument(
        name, 1, "PLN", id=instrument_id, asset_class_name="Obligacje skarbowe polskie", fallback_order=()
    )


def _terms(name: str, sold: date, margin: str, rates: tuple[Decimal | None, ...]) -> SeriesTerms:
    return SeriesTerms(
        name, "PL0", sold, sold.replace(day=28), Decimal(100), Decimal("99.9"), Decimal(margin), rates, ()
    )


EDO1035 = _instrument(10, "EDO1035")
COI0528 = _instrument(11, "COI0528")
ROR0927 = _instrument(12, "ROR0927")
ROS1026 = _instrument(13, "ROS1026")
TOS0828 = _instrument(14, "TOS0828")
INSTRUMENTS = {i.id: i for i in (EDO1035, COI0528, ROR0927, ROS1026, TOS0828)}
DATA = BondData(
    {
        10: BondSeries(10, "EDO1035", _terms("EDO1035", date(2025, 10, 1), "0.02", (Decimal("0.0560"), None))),
        11: BondSeries(
            11, "COI0528", _terms("COI0528", date(2024, 5, 1), "0.0125", (Decimal("0.0655"), Decimal("0.0615")))
        ),
        12: BondSeries(12, "ROR0927", _terms("ROR0927", date(2026, 9, 1), "0", (Decimal("0.06"),) * 12)),
        14: BondSeries(14, "TOS0828", _terms("TOS0828", date(2025, 8, 1), "0", (Decimal("0.0565"),))),
    },
    readings=(CpiReading(2026, 8, Decimal("103.0"), None), CpiReading(2026, 3, Decimal("103.5"), None)),
)


def _lot(day: date, quantity: int) -> Lot:
    return Lot(day, Decimal(quantity), Decimal(100 * quantity), Decimal(100 * quantity), opened_by=1)


def test_an_edo_shows_its_next_anniversary_with_the_new_rate_within_twelve_months() -> None:
    position = Position(1, 10, (_lot(date(2025, 10, 15), 10),))

    [event] = bond_calendar([position], INSTRUMENTS, [BONDS, IKE], DATA, TODAY, None)

    assert (event.kind, event.day, event.account, event.instrument) == (
        EventKind.ANNIVERSARY,
        date(2026, 10, 15),
        BONDS,
        EDO1035,
    )
    # CPI of August 2026 (two months before October) 3% + margin 2%
    assert event.rate is not None and event.rate.rate == Decimal("0.05")
    assert (event.period, event.label) == (2, RateLabel.ESTIMATED_CPI)
    assert event.rate_text == "5,00 % · rok 2"
    assert event.quantity == Decimal(10) and event.gross is None and event.net is None


def test_a_coi_shows_its_coupon_with_belka_and_the_anniversary_of_its_next_year() -> None:
    position = Position(1, 11, (_lot(date(2024, 5, 20), 10),))

    coupon, anniversary = bond_calendar([position], INSTRUMENTS, [BONDS, IKE], DATA, TODAY, None)

    # The third year's rate from CPI of March 2026: 3.5% + 1.25% margin, a coupon of 4.75 zł a bond, 0.90 zł tax
    assert (coupon.kind, coupon.day, coupon.period) == (EventKind.COUPON, date(2027, 5, 20), 3)
    assert (coupon.gross, coupon.net, coupon.label) == (Decimal("47.50"), Decimal("38.50"), RateLabel.ESTIMATED_CPI)
    # The fourth year's CPI (March 2027) is not published, so the last reading forecasts it
    assert (anniversary.kind, anniversary.day, anniversary.period) == (EventKind.ANNIVERSARY, date(2027, 5, 20), 4)
    assert anniversary.label is RateLabel.FORECAST_CPI


def test_a_ror_shows_each_monthly_coupon_and_its_maturity_but_no_anniversary() -> None:
    position = Position(2, 12, (_lot(date(2026, 9, 10), 10),))

    events = bond_calendar([position], INSTRUMENTS, [BONDS, IKE], DATA, TODAY, None)

    coupons = [e for e in events if e.kind is EventKind.COUPON]
    assert [c.day for c in coupons] == [date(2026, m, 10) for m in (10, 11, 12)] + [
        date(2027, m, 10) for m in range(1, 9)
    ]
    # 6% a year is 0.50 zł a month; an IKE withholds nothing
    assert all(c.gross == c.net == Decimal("5.00") for c in coupons)
    assert coupons[0].rate_text == "6,00 % · miesiąc 1"
    [maturity] = [e for e in events if e.kind is EventKind.MATURITY]
    assert (maturity.day, maturity.gross, maturity.net) == (date(2027, 9, 10), Decimal("1005.00"), Decimal("1005.00"))
    assert events[-1] is maturity


def test_a_maturity_pays_the_nominal_with_the_interest_less_the_tax() -> None:
    position = Position(1, 12, (_lot(date(2026, 9, 10), 10),))

    [*_, maturity] = bond_calendar([position], INSTRUMENTS, [BONDS, IKE], DATA, TODAY, None)

    # 0.50 zł of interest a bond, 0.095 zł rounded to 0.10 zł of tax
    assert (maturity.gross, maturity.net) == (Decimal("1005.00"), Decimal("1004.00"))


def test_the_calendar_runs_from_tomorrow_to_the_same_day_next_year() -> None:
    # An anniversary today is the current period, no longer coming; the next one is twelve months away
    position = Position(1, 10, (_lot(date(2025, 10, 8), 10),))

    [event] = bond_calendar([position], INSTRUMENTS, [BONDS, IKE], DATA, TODAY, None)

    assert (event.day, event.period) == (date(2027, 10, 8), 3)


def test_a_series_not_valued_shows_only_its_maturity_without_amounts() -> None:
    position = Position(1, 13, (_lot(date(2020, 10, 20), 3),))

    [event] = bond_calendar([position], INSTRUMENTS, [BONDS, IKE], DATA, TODAY, None)

    assert (event.kind, event.day, event.gross, event.net, event.rate) == (
        EventKind.MATURITY,
        date(2026, 10, 20),
        None,
        None,
        None,
    )


def test_the_calendar_follows_the_view_scope_and_orders_events_by_day() -> None:
    positions = [
        Position(1, 11, (_lot(date(2024, 5, 20), 10),)),
        Position(1, 10, (_lot(date(2025, 10, 15), 10),)),
        Position(2, 10, (_lot(date(2025, 11, 3), 5),)),
    ]

    everything = bond_calendar(positions, INSTRUMENTS, [BONDS, IKE], DATA, TODAY, None)
    on_ike = bond_calendar(positions, INSTRUMENTS, [BONDS, IKE], DATA, TODAY, 2)

    assert [e.day for e in everything] == [date(2026, 10, 15), date(2026, 11, 3), date(2027, 5, 20), date(2027, 5, 20)]
    assert [(e.account, e.day) for e in on_ike] == [(IKE, date(2026, 11, 3))]


def test_a_tos_shows_its_yearly_capitalisation_at_its_fixed_rate() -> None:
    position = Position(1, 14, (_lot(date(2025, 8, 12), 10),))

    [event] = bond_calendar([position], INSTRUMENTS, [BONDS, IKE], DATA, TODAY, None)

    assert (event.kind, event.day, event.rate_text, event.label) == (
        EventKind.ANNIVERSARY,
        date(2027, 8, 12),
        "5,65 % · rok 3",
        None,
    )
