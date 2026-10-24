"""The login screen (spec 2.1, ADR-0010, issue #195): opened at every start in the default Theme, since the list of
Users holds only pseudonyms and hashes. A list of the pseudonyms with the password, or the creation of a User when
there are none or "Nowy użytkownik" is chosen."""

from collections.abc import Callable

from nicegui import ui

from financial_app.domain.themes import Theme
from financial_app.domain.users import password_error
from financial_app.persistence.paths import USERS_FILE
from financial_app.persistence.users import User, UserError, UserStore
from financial_app.ui.shell import APP_LOGO, APP_TITLE
from financial_app.ui.theme import apply_theme

PASSWORD_IS_A_LOCK = (
    "Hasło blokuje dostęp do aplikacji, ale nie szyfruje danych: pliki w folderze aplikacji może otworzyć każdy, "
    "kto korzysta z tego konta Windows."
)
RESET_STEPS = (
    f"Hasło można zresetować ręcznie: zamknij aplikację, otwórz plik {USERS_FILE} w folderze danych KAPITA "
    'i usuń z wpisu użytkownika linię "password_hash". Przy następnym logowaniu ustawisz nowe hasło. '
    "Dane użytkownika zostają nietknięte."
)
NO_PASSWORD_YET = "Ten użytkownik nie ma hasła. Wpisane hasło zostanie ustawione."


def build_login(store: UserStore, on_signed_in: Callable[[User], None]) -> None:
    """Draw the login screen on the page being built; ``on_signed_in`` gets the User who got in."""
    apply_theme(Theme.LIGHT)
    with ui.column().classes("w-full items-center pt-16").mark("login"):
        ui.image(APP_LOGO).props("no-transition no-spinner").classes("w-16 h-16").mark("login-logo")
        ui.label(APP_TITLE).classes("text-2xl font-bold tracking-widest")
        form = _LoginForm(store, on_signed_in)
        form.build()


class _LoginForm:
    def __init__(self, store: UserStore, on_signed_in: Callable[[User], None]) -> None:
        self.store = store
        self.on_signed_in = on_signed_in
        self.creating = not store.users()

    @ui.refreshable_method
    def build(self) -> None:
        with ui.card().classes("w-96 gap-3"):
            if self.creating:
                self._creating()
            else:
                self._signing_in()
            ui.label(PASSWORD_IS_A_LOCK).classes("text-xs k-muted").mark("password-is-a-lock")

    def _show(self, creating: bool) -> None:
        self.creating = creating
        self.build.refresh()

    def _signing_in(self) -> None:
        users = self.store.users()
        ui.label("Zaloguj się").classes("text-lg font-bold")
        pseudonym = ui.select([u.pseudonym for u in users], value=users[0].pseudonym, label="Użytkownik")
        pseudonym.classes("w-full").mark("login-user")
        password = ui.input("Hasło", password=True, password_toggle_button=True).classes("w-full")
        password.mark("login-password")
        hint = ui.label().classes("text-xs k-muted").mark("login-hint")

        def refresh_hint() -> None:
            hint.text = NO_PASSWORD_YET if self.store.find(pseudonym.value).password_hash is None else ""

        pseudonym.on_value_change(refresh_hint)
        refresh_hint()
        error = ui.label().classes("text-negative").mark("login-error")

        def sign_in() -> None:
            try:
                user = self.store.find(pseudonym.value)
                if user.password_hash is None:
                    user = self.store.set_password(user, password.value)
                else:
                    user = self.store.sign_in(pseudonym.value, password.value)
            except UserError as problem:
                error.text = str(problem)
                return
            self.on_signed_in(user)

        password.on("keydown.enter", sign_in)
        ui.button("Zaloguj", on_click=sign_in).classes("w-full").mark("login-submit")
        with ui.row().classes("w-full justify-between"):
            ui.button("Nowy użytkownik", on_click=lambda: self._show(True)).props("flat no-caps").mark("login-new")
            ui.button("Nie pamiętam hasła", on_click=self._forgotten).props("flat no-caps").mark("login-forgotten")

    def _creating(self) -> None:
        ui.label("Nowy użytkownik").classes("text-lg font-bold")
        pseudonym = ui.input("Pseudonim").classes("w-full").mark("new-user-pseudonym")
        password = ui.input("Hasło", password=True, password_toggle_button=True).classes("w-full")
        password.mark("new-user-password")
        repeated = ui.input("Powtórz hasło", password=True).classes("w-full").mark("new-user-repeated")
        error = ui.label().classes("text-negative").mark("new-user-error")

        def create() -> None:
            if problem := password_error(password.value, repeated.value):
                error.text = problem
                return
            try:
                user = self.store.create(pseudonym.value, password.value)
            except UserError as refusal:
                error.text = str(refusal)
                return
            self.on_signed_in(user)

        repeated.on("keydown.enter", create)
        ui.button("Utwórz i zaloguj", on_click=create).classes("w-full").mark("new-user-submit")
        if self.store.users():
            ui.button("Wróć do logowania", on_click=lambda: self._show(False)).props("flat no-caps")

    def _forgotten(self) -> None:
        with ui.dialog() as dialog, ui.card().classes("w-96").mark("forgotten-password"):
            ui.label("Nie pamiętam hasła").classes("text-lg font-bold")
            ui.label(RESET_STEPS)
            ui.label(PASSWORD_IS_A_LOCK).classes("text-sm k-muted")
            ui.button("Zamknij", on_click=dialog.close).props("flat")
        dialog.on("hide", dialog.delete)
        dialog.open()
