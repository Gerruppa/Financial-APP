"""Ustawienia > Użytkownik: change the pseudonym, change the password, delete the User (spec 2.1, issue #196)."""

from collections.abc import Callable
from dataclasses import dataclass, field

from nicegui import ui

from financial_app.domain.users import PASSWORDS_DIFFER, clean_pseudonym, password_error
from financial_app.persistence.users import User, UserError, UserStore


@dataclass
class UserSection:
    """The Użytkownik card for ``user``. ``on_changed`` gets the User after a new pseudonym or password (the window
    redraws when the pseudonym differs); ``on_deleted`` gets the password once it was checked, signs the User out and
    deletes them."""

    store: UserStore
    user: User
    on_changed: Callable[[User], None]
    on_deleted: Callable[[str], None]
    card: ui.card = field(init=False)

    def build(self) -> None:
        self.card = ui.card().classes("w-full max-w-4xl").mark("user-section")
        with self.card:
            ui.label("Użytkownik").classes("text-xl font-bold")
            self._pseudonym()
            ui.separator()
            self._password()
            ui.separator()
            self._deletion()

    def _pseudonym(self) -> None:
        ui.label("Pseudonim").classes("font-bold")
        pseudonym = ui.input(value=self.user.pseudonym).classes("w-full max-w-sm").mark("user-pseudonym")
        error = ui.label().classes("text-negative").mark("user-rename-error")

        def rename() -> None:
            try:
                self.user = self.store.rename(self.user, pseudonym.value)
            except UserError as refusal:
                error.text = str(refusal)
                return
            error.text = ""
            ui.notify("Zmieniono pseudonim.", type="positive")
            self.on_changed(self.user)

        ui.button("Zmień pseudonim", on_click=rename).props("no-caps").mark("user-rename")

    def _password(self) -> None:
        ui.label("Hasło").classes("font-bold")
        fields = [
            ui.input(label, password=True, password_toggle_button=True).classes("w-full max-w-sm").mark(marker)
            for label, marker in (
                ("Obecne hasło", "user-password-current"),
                ("Nowe hasło", "user-password-new"),
                ("Powtórz nowe hasło", "user-password-repeated"),
            )
        ]
        current, new, repeated = fields
        error = ui.label().classes("text-negative").mark("user-password-error")

        def change() -> None:
            if problem := password_error(new.value) or (PASSWORDS_DIFFER if new.value != repeated.value else None):
                error.text = problem
                return
            try:
                self.user = self.store.change_password(self.user, current.value, new.value)
            except UserError as refusal:
                error.text = str(refusal)
                return
            error.text = ""
            for password in fields:
                password.value = ""
            ui.notify("Zmieniono hasło.", type="positive")
            self.on_changed(self.user)

        ui.button("Zmień hasło", on_click=change).props("no-caps").mark("user-password-change")

    def _deletion(self) -> None:
        ui.label("Usuń użytkownika").classes("font-bold text-negative")
        ui.label(
            "Kasuje cały folder użytkownika: bazę, kopie zapasowe i dziennik. Tej operacji nie można cofnąć."
        ).classes("text-sm")
        ui.button("Usuń użytkownika…", icon="delete_forever", on_click=self._ask).props("color=negative no-caps").mark(
            "user-delete"
        )

    def _ask(self) -> None:
        # Made in the card, which outlives the dialog (see CLAUDE.md on dialogs)
        with self.card:
            dialog = ui.dialog()
        dialog.on("hide", dialog.delete)

        def delete() -> None:
            try:
                self.store.check_password(self.user, password.value)
            except UserError as refusal:
                error.text = str(refusal)
                return
            dialog.close()
            self.on_deleted(password.value)

        with dialog, ui.card():
            ui.label(f"Usunąć użytkownika {self.user.pseudonym}?").classes("text-lg font-bold text-negative")
            ui.label(
                "Zniknie jego baza razem z kopiami zapasowymi. Aby potwierdzić, wpisz hasło i pseudonym użytkownika."
            ).classes("text-sm")
            password = ui.input("Hasło", password=True, password_toggle_button=True).classes("w-full")
            password.mark("user-delete-password")
            typed = ui.input("Pseudonym").classes("w-full").mark("user-delete-pseudonym")
            error = ui.label().classes("text-negative").mark("user-delete-error")
            with ui.row().classes("w-full justify-end"):
                ui.button("Anuluj", on_click=dialog.close).props("flat").mark("user-delete-cancel")
                confirm = ui.button("Usuń", on_click=delete).props("color=negative").mark("user-delete-confirm")
            confirm.disable()
            typed.on_value_change(
                lambda e: confirm.set_enabled(
                    clean_pseudonym(e.value or "").casefold() == self.user.pseudonym.casefold()
                )
            )
        dialog.open()
