# `domain/account_rules.py`

Which Instruments an Account may buy, by its Account Type; it changes no calculation. `product_of(instrument)` gives one `Product`: a Bond Series (`is_bond_series`) is `RETAIL_BOND`, a metal by weight or Type `METAL`, crypto by Type or the Kryptowaluty class `CRYPTO`, a Fund `FUND`, stock, ETF, ETC and bonds off the Catalyst or abroad `SECURITY`, anything left as Inne `OTHER`. `_ALLOWED` maps each `AccountType` to its Products (`allowed_products`, `can_hold`, `products_text` for the Polish list):

| Account Type | May buy |
|---|---|
| Regular | securities, funds, crypto, Other |
| IKE, IKZE, OIPE | retail bonds, securities, funds, Other (spec 3.1: bonds held on an IKE stay on an IKE Account) |
| OKI | securities, funds, Other |
| PPK | funds |
| Bonds | retail bonds |
| Deposit | nothing (Term Deposits are their own tab) |
| Other | physical metals, crypto, Other |

`refusal(account, instrument)` is the Polish message, or `None`; it is the one text the dialog's `FormError`, the rule dialog's `RecurringRuleError` and the `NotAllowed` save warning all use. Where it applies: `TransactionForm._check_holds` (Buy, DRIP, and a Security Transfer's target; an edit keeps the Instrument its Transaction already had) and `_instruments_for` (`FormLayout.instruments`, the Instrument select narrowed for a Buy or DRIP); `ui/recurring_rules.py` refuses a rule that buys what its Account may not; `save_warnings._not_allowed` only warns for imports (sheet, XTB, Reconciliation) and confirmed Drafts, which enter history. Existing Transactions are never rewritten. Tests: `tests/test_account_rules_domain.py`.
