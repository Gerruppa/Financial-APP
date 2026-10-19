# `sources/nbp.py`

`NbpRates.before(currency, day)` gives the NBP Rate (D-1, table A) from the NBP API, cached per currency and day in SQLite (`persistence/nbp_rates.py`, so `sources/` sits above `persistence/`), and `latest(currency)` values foreign Positions until automatic valuation (#3); a missing rate raises `MissingNbpRateError` and blocks the save. Its `fetch` and `today` are injectable, so tests run on saved responses in `tests/fixtures/nbp/` without the network; `build_shell(engine, rates)` takes a test instance.
