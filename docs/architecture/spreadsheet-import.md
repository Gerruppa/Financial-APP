# `domain/spreadsheet_import.py`

Reads the Transakcje sheet's columns, classifies tickers (`EXCH:SYM`, bonds `TYP-DDMMRR` → Bond Series, `Gotówka`, `Waluty_<CUR>`), builds the Transaction for each row (Actual Amount = the sheet's "Total PLN") and fingerprints rows so a re-import skips them.
