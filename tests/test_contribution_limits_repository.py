"""Saving Contribution Limits (issue #95, spec 8.1): 2026 seeded, a row per year added, edited and removed."""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountType
from financial_app.domain.contribution_limits import ContributionLimitError
from financial_app.persistence.contribution_limits import add_year, delete_year, load_limits, set_limits
from financial_app.persistence.db import init_db

IKE, IKZE, OIPE = AccountType.IKE, AccountType.IKZE, AccountType.OIPE


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def test_2026_comes_seeded_with_the_ministrys_limits(engine: Engine) -> None:
    assert load_limits(engine) == {2026: {IKE: Decimal(28260), IKZE: Decimal(11304), OIPE: Decimal(28260)}}


def test_a_year_is_added_empty_then_its_limits_entered_and_cleared(engine: Engine) -> None:
    add_year(engine, 2027)
    assert load_limits(engine)[2027] == {IKE: None, IKZE: None, OIPE: None}

    set_limits(engine, 2027, {IKE: None, IKZE: Decimal("16956"), OIPE: None})
    set_limits(engine, 2026, {IKE: None, IKZE: Decimal(11304), OIPE: Decimal(28260)})

    limits = load_limits(engine)
    assert limits[2027] == {IKE: None, IKZE: Decimal(16956), OIPE: None}
    assert limits[2026][IKE] is None
    assert list(limits) == [2026, 2027]


def test_only_a_year_without_limits_can_be_removed(engine: Engine) -> None:
    add_year(engine, 2027)
    with pytest.raises(ContributionLimitError, match="Najpierw usuń limity roku 2026"):
        delete_year(engine, 2026)

    delete_year(engine, 2027)

    assert list(load_limits(engine)) == [2026]
