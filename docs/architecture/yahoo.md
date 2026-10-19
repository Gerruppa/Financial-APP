# `sources/yahoo.py`

`YahooSource(fetch).quote(symbol, currency)`, from the chart API: the price in the Instrument's quote currency (GBp ÷ 100; crypto in another currency through Yahoo's own `XXXYYY=X` rate; any other mismatch is a `PriceSourceError`), on the exchange's day (`regularMarketTime` + `gmtoffset`). Tests run on `tests/fixtures/yahoo/`.
