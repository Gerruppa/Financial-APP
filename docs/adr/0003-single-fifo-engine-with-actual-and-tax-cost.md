# One FIFO lot engine with Actual and Tax cost per Lot

The spreadsheet has two FIFO implementations (Portfolio and Sell Summary) that disagree on splits, fees, dividends and ordering. We use a single lot engine for Portfolio, realised results and PIT-38. Each Lot carries two costs: the Actual Amount (what really left the Account, incl. fees and broker FX spread) and the Tax Amount (at the NBP D-1 rate, as Polish tax law requires). Foreign cash is also held as Lots so that FX gains can be measured and excluded per Account. Average-cost was rejected: Polish tax law requires FIFO.
