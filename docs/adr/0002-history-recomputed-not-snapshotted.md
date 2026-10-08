# Portfolio history is recomputed, not snapshotted

The source spreadsheet writes a daily snapshot from a cloud trigger and freezes it, so later corrections never reach history. A local app cannot run daily while the PC is off, so History is recomputed from Transactions plus locally cached historical prices and FX rates. This gives complete charts from the first Transaction, including imported data, and makes corrections retroactive. The spreadsheet's stored Historia is imported only as a comparison fixture, never displayed.
