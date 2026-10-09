"""The NBP Rate (D-1) from the NBP API with a local cache (issue #15), on saved NBP responses, without the network."""

import json
from datetime import date
from decimal import Decimal
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

import pytest
from sqlalchemy import Engine

from financial_app.domain.currencies import MissingNbpRateError, NbpRate
from financial_app.persistence.db import init_db
from financial_app.sources.nbp import NbpRates

FIXTURES = Path(__file__).parent / "fixtures" / "nbp"
URL_PREFIX = "https://api.nbp.pl/api/exchangerates/rates/a/"
URL_SUFFIX = "/?format=json"
URL = URL_PREFIX + "{}" + URL_SUFFIX


class SavedNbp:
    """Answers NBP API URLs from the saved responses in ``fixtures/nbp`` and counts the requests."""

    def __init__(self, extra: dict[str, str] | None = None, error: OSError | None = None) -> None:
        self.extra = extra or {}
        self.error = error
        self.requests: list[str] = []

    def __call__(self, url: str) -> str | None:
        self.requests.append(url)
        if self.error is not None:
            raise self.error
        if url in self.extra:
            return self.extra[url]
        path = url.removeprefix(URL_PREFIX).removesuffix(URL_SUFFIX)
        saved = FIXTURES / f"{path.replace('/', '_')}.json"
        return saved.read_text(encoding="utf-8") if saved.exists() else None


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


def _rates(engine: Engine, nbp: SavedNbp, today: date = date(2026, 10, 9)) -> NbpRates:
    return NbpRates(engine, fetch=nbp, today=lambda: today)


def test_rate_after_a_holiday_is_the_last_business_days_rate(engine: Engine) -> None:
    nbp = SavedNbp()

    # 6 January (Epiphany) has no table, so a Transaction on the 7th takes Monday the 5th
    rate = _rates(engine, nbp).before("USD", date(2026, 1, 7))

    assert rate == NbpRate("USD", Decimal("3.6045"), date(2026, 1, 5), "002/A/NBP/2026")
    assert nbp.requests == [URL.format("usd/2025-12-24/2026-01-06")]


def test_rate_after_a_weekend_and_a_holiday_is_the_last_business_days_rate(engine: Engine) -> None:
    # Easter Sunday and Monday (5-6 April 2026) follow the weekend, so Tuesday the 7th takes Friday the 3rd
    rate = _rates(engine, SavedNbp()).before("USD", date(2026, 4, 7))

    assert rate == NbpRate("USD", Decimal("3.7058"), date(2026, 4, 3), "065/A/NBP/2026")


def test_rate_fetched_once_comes_from_the_cache(engine: Engine) -> None:
    nbp = SavedNbp()
    first = _rates(engine, nbp).before("USD", date(2026, 1, 7))

    # A new instance, as after a restart, still finds it in the database
    again = _rates(engine, nbp).before("usd", date(2026, 1, 7))

    assert again == first
    assert len(nbp.requests) == 1


def test_unknown_currency_has_no_rate(engine: Engine) -> None:
    with pytest.raises(MissingNbpRateError, match="Brak kursu NBP XYZ"):
        _rates(engine, SavedNbp()).before("XYZ", date(2026, 4, 7))


def test_network_failure_is_a_missing_rate_and_is_not_cached(engine: Engine) -> None:
    offline = SavedNbp(error=OSError("no network"))
    with pytest.raises(MissingNbpRateError, match="połączenie z internetem"):
        _rates(engine, offline).before("USD", date(2026, 1, 7))

    online = SavedNbp()
    _rates(engine, online).before("USD", date(2026, 1, 7))
    assert len(online.requests) == 1


def test_rate_for_tomorrow_is_known_once_todays_table_is_out(engine: Engine) -> None:
    published = {
        "table": "A",
        "code": "USD",
        "rates": [{"no": "196/A/NBP/2026", "effectiveDate": "2026-10-08", "mid": 3.9132}],
    }
    nbp = SavedNbp(extra={URL.format("usd/2026-09-25/2026-10-08"): json.dumps(published)})

    rate = _rates(engine, nbp, today=date(2026, 10, 8)).before("USD", date(2026, 10, 9))

    assert rate.published_on == date(2026, 10, 8)


def test_rate_for_tomorrow_is_not_guessed_before_todays_table_is_out(engine: Engine) -> None:
    published = {
        "table": "A",
        "code": "USD",
        "rates": [{"no": "195/A/NBP/2026", "effectiveDate": "2026-10-07", "mid": 3.9111}],
    }
    nbp = SavedNbp(extra={URL.format("usd/2026-09-25/2026-10-08"): json.dumps(published)})

    with pytest.raises(MissingNbpRateError, match="jeszcze"):
        _rates(engine, nbp, today=date(2026, 10, 8)).before("USD", date(2026, 10, 9))


def test_rate_for_a_later_future_day_is_not_known_yet(engine: Engine) -> None:
    nbp = SavedNbp()

    with pytest.raises(MissingNbpRateError, match="jeszcze"):
        _rates(engine, nbp, today=date(2026, 10, 8)).before("USD", date(2026, 10, 20))
    assert nbp.requests == []


def test_server_error_is_a_missing_rate_without_blaming_the_connection(engine: Engine) -> None:
    failing = SavedNbp(error=HTTPError(URL, 500, "Internal Server Error", Message(), None))

    with pytest.raises(MissingNbpRateError, match="Serwis NBP"):
        _rates(engine, failing).before("USD", date(2026, 1, 7))


def test_malformed_answer_is_a_missing_rate(engine: Engine) -> None:
    garbled = SavedNbp(extra={URL.format("usd/2025-12-24/2026-01-06"): "<html>maintenance</html>"})

    with pytest.raises(MissingNbpRateError, match="Nieprawidłowa odpowiedź NBP"):
        _rates(engine, garbled).before("USD", date(2026, 1, 7))


def test_latest_rate_is_the_one_before_today(engine: Engine) -> None:
    rate = _rates(engine, SavedNbp(), today=date(2026, 1, 7)).latest("USD")

    assert rate.published_on == date(2026, 1, 5)


def test_latest_rate_does_not_retry_a_failed_fetch_at_once(engine: Engine) -> None:
    offline = SavedNbp(error=OSError("no network"))
    rates = _rates(engine, offline, today=date(2026, 1, 7))

    for _ in range(3):
        with pytest.raises(MissingNbpRateError):
            rates.latest("USD")

    assert len(offline.requests) == 1
