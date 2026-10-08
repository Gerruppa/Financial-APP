# Fix spreadsheet bugs instead of replicating them

The app aims at the same logic as the inwestomat v2.0.1 spreadsheet and is verified against it with parity tests (frozen prices, 0.01 PLN tolerance). Known spreadsheet bugs (e.g. GBp not divided by 100 in one source, FX failure silently giving 0 PLN, XIRR limited to rows 2–61, rate parsing rounding 6.8% to 7%) are fixed, and every fix that changes a number is recorded as an explicit expected deviation in the parity tests rather than reproduced for penny-exact agreement.
