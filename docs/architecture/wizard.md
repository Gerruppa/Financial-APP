# Step-by-step window (#268)

`ui/wizard.py` `Wizard(prefix, steps, width)` is the shell of every step-by-step window: a `ui.dialog` with a card marked `<prefix>-wizard`, a header "Krok N z M: <title>" marked `<prefix>-step-<n>`, the current step's body and a row of `<prefix>-back` ("Wstecz", from step 2), `<prefix>-close` ("Zamknij") and `<prefix>-next` ("Dalej", up to the last step, disabled until the step is ready). Each `WizardStep(title, body)` draws its body on every `render` and returns whether "Dalej" may follow. `open` starts on step 1, `go(n)` jumps to a step (e.g. after loading a file), `render` redraws the current one after a choice, `close` closes the window and keeps the step.

The user keeps the state the steps share (choices, loaded files) and makes the `Wizard` inside an element that outlives it, such as its card in Ustawienia: NiceGUI deletes a dialog with the element it was opened in (CLAUDE.md).

Users: the crypto import window (`ui/crypto_import.py`, prefix `crypto`), the first Recurring Rule (`ui/first_rule.py`, prefix `first-rule`, see `recurring-rules.md`) and the first-run window (`ui/first_run.py`, prefix `first-run`, see `first-run.md`). `tests/test_wizard.py` checks the header, "Wstecz", and "Dalej" held until a step is ready.
