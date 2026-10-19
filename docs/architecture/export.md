# Export

`domain/export.py` builds the Transakcje rows for export (every type, the commission with its "Waluta prowizji" (#124), the Actual and Tax Amounts, origin, comment); `sources/export.py` writes them to CSV (UTF-8 with BOM, `;`, decimal comma, day-first dates) or XLSX. The Transakcje tab's "Eksportuj CSV" and "Eksportuj XLSX" buttons hand the file to the browser.
