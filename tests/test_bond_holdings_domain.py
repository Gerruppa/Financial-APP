"""The Obligacje tab's table (L-4, spec 3.4.1): each Bond Series held on an Account, expanding to its Lots, with what
was paid in, the current period and its rate, the gross and net value, the next anniversary and the maturity."""

from datetime import date
from decimal import Decimal

from financial_app.domain.accounts import Account, AccountType
from financial_app.domain.bond_holdings import SeriesHolding, bond_holdings
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


def _terms(name: str, rates: tuple[Decimal | None, ...]) -> SeriesTerms:
    return SeriesTerms(
        name, "PL0", date(2026, 5, 1), date(2026, 5, 31), Decimal(100), Decimal("99.9"), Decimal("0.02"), rates, ()
    )


EDO0536 = _instrument(10, "EDO0536")
EDO0535 = _instrument(11, "EDO0535")
STOCK = Instrument("CD Projekt", 2, "PLN", id=12, asset_class_name="Akcje polskie", fallback_order=())
DATA = BondData(
    {
        10: BondSeries(10, "EDO0536", _terms("EDO0536", (Decimal("0.0535"),) + (None,) * 9)),
        11: BondSeries(11, "EDO0535", _terms("EDO0535", (Decimal("0.0565"),) + (None,) * 9)),
    },
    (CpiReading(2026, 3, Decimal("103.0"), None),),
)


def _lot(day: date, quantity: int) -> Lot:
    return Lot(day, Decimal(quantity), Decimal(100 * quantity), Decimal(100 * quantity))


def _holdings(positions: list[Position], account_id: int | None = None) -> list[SeriesHolding]:
    instruments = {i.id: i for i in (EDO0536, EDO0535, STOCK)}
    return bond_holdings(positions, instruments, [BONDS, IKE], DATA, TODAY, account_id)


def test_a_series_sums_its_lots_and_shows_the_oldest_lots_period() -> None:
    position = Position(1, 10, (_lot(date(2026, 5, 22), 10), _lot(date(2026, 5, 29), 5)))

    [holding] = _holdings([position])

    assert holding.account == BONDS
    assert holding.instrument == EDO0536
    assert holding.quantity == Decimal(15)
    assert holding.paid == Decimal(1500)
    first, second = holding.lots
    assert first.value is not None and first.value.value == Decimal("102.04")
    # 132 days at 5.35% give the second Lot 101.93 zł a bond
    assert second.gross == Decimal("509.65")
    assert holding.gross == Decimal("1530.05")
    assert holding.current is not None and holding.current.period == 1
    assert holding.next_anniversary == date(2027, 5, 22)
    assert holding.maturity == date(2036, 5, 22)
    # The 3 zł fee takes all the interest, so nothing is taxed and the net is what was paid
    assert holding.net == Decimal(1500)


def test_the_tax_follows_the_accounts_tax_regime() -> None:
    lot = _lot(date(2025, 5, 22), 10)

    taxed, free = _holdings([Position(1, 11, (lot,)), Position(2, 11, (lot,))])

    # A year at 5.65%, then 139 days at 5.00% (CPI 3% + 2% margin, estimated): 107.66 zł a bond
    assert taxed.gross == free.gross == Decimal("1076.60")
    assert taxed.label is RateLabel.ESTIMATED_CPI
    # The 3 zł fee, then 19% of the 4.66 zł profit (0.89 zł) on the Bonds Account
    assert taxed.net == Decimal("1037.70")
    assert free.net == Decimal("1046.60")


def test_only_bond_series_of_the_scope_are_listed_largest_first() -> None:
    positions = [
        Position(1, 10, (_lot(date(2026, 5, 22), 1),)),
        Position(2, 11, (_lot(date(2025, 5, 22), 10),)),
        Position(1, 12, (_lot(date(2026, 5, 22), 10),)),
    ]

    assert [h.instrument.name for h in _holdings(positions)] == ["EDO0535", "EDO0536"]
    assert [h.instrument.name for h in _holdings(positions, account_id=1)] == ["EDO0536"]


def test_a_series_not_valued_yet_stays_at_cost_without_a_net_value() -> None:
    coi = _instrument(13, "COI0530")

    [holding] = bond_holdings([Position(1, 13, (_lot(date(2026, 5, 22), 10),))], {13: coi}, [BONDS], DATA, TODAY, None)

    assert holding.gross == Decimal(1000)
    assert holding.net is None
    assert holding.current is None
    assert holding.maturity == date(2030, 5, 22)
