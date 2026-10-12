# An early bond redemption picks its Lot instead of FIFO

ADR-0003 sells every Position's Lots first in, first out. Retail treasury bonds do not work that way: the bank redeems the purchase the investor names, each purchase earns from its own date, and the early-redemption fee and Belka depend on that purchase's accrued interest. So a Sell of a Bond Series names its Lot (the dialog defaults to the oldest), and the FIFO engine takes the units from that Lot alone; every other Instrument keeps FIFO. A Sell without a named Lot (an imported one, say) falls back to FIFO, which matches the default.
