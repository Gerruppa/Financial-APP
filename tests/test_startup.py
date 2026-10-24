"""Smoke test of the real entry point: one command shows the login screen, and signing in builds the User's database
and shows the window."""

from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation

from financial_app import app
from financial_app.persistence.db import init_db
from financial_app.persistence.paths import BACKUPS_DIR, DATABASE_FILE
from financial_app.persistence.users import UserStore

MAIN_FILE = Path(__file__).resolve().parents[1] / "main.py"


def _create_user(user: User, pseudonym: str, password: str) -> None:
    user.find(marker="new-user-pseudonym").type(pseudonym)
    user.find(marker="new-user-password").type(password)
    user.find(marker="new-user-repeated").type(password)
    user.find(marker="new-user-submit").click()


def _sign_in(user: User, password: str) -> None:
    user.find(marker="login-password").type(password)
    user.find(marker="login-submit").click()


async def test_first_start_opens_on_creating_a_user_and_shows_the_dashboard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))

    async with user_simulation(main_file=MAIN_FILE) as user:
        await user.open("/")
        await user.should_see("Nowy użytkownik")
        await user.should_see("nie szyfruje")
        _create_user(user, "Anna", "sekret")

        await user.should_see("Dashboard")
    [anna] = UserStore(tmp_path).users()
    assert (tmp_path / anna.id / DATABASE_FILE).exists()


async def test_existing_data_moves_to_the_first_user(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    init_db(tmp_path / DATABASE_FILE).dispose()

    async with user_simulation(main_file=MAIN_FILE) as user:
        await user.open("/")
        _create_user(user, "Anna", "sekret")
        await user.should_see("Dashboard")

    [anna] = UserStore(tmp_path).users()
    assert (tmp_path / anna.id / DATABASE_FILE).exists()
    assert not (tmp_path / DATABASE_FILE).exists()


async def test_each_sign_in_backs_up_the_users_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    store = UserStore(tmp_path)
    anna = store.create("Anna", "sekret")
    init_db(store.folder(anna) / DATABASE_FILE).dispose()

    async with user_simulation(main_file=MAIN_FILE) as user:
        await user.open("/")
        await user.should_see("Zaloguj się")
        _sign_in(user, "sekret")
        await user.should_see("Dashboard")

    assert len(list((store.folder(anna) / BACKUPS_DIR).iterdir())) == 1


async def test_wrong_password_is_refused_without_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    UserStore(tmp_path).create("Anna", "sekret")

    async with user_simulation(main_file=MAIN_FILE) as user:
        await user.open("/")
        for _ in range(3):
            user.find(marker="login-password").clear().type("zle")
            user.find(marker="login-submit").click()
            await user.should_see("Nieprawidłowe hasło")
        user.find(marker="login-password").clear().type("sekret")
        user.find(marker="login-submit").click()

        await user.should_see("Dashboard")


async def test_forgotten_password_explains_the_reset_by_hand(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    UserStore(tmp_path).create("Anna", "sekret")

    async with user_simulation(main_file=MAIN_FILE) as user:
        await user.open("/")
        user.find(marker="login-forgotten").click()

        await user.should_see("password_hash")


async def test_user_without_a_hash_sets_a_new_password(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    store = UserStore(tmp_path)
    anna = store.create("Anna", "sekret")
    (tmp_path / "users.json").write_text(f'{{"users": [{{"id": "{anna.id}", "pseudonym": "Anna"}}]}}', encoding="utf-8")

    async with user_simulation(main_file=MAIN_FILE) as user:
        await user.open("/")
        await user.should_see("nie ma hasła")
        _sign_in(user, "nowe-haslo")
        await user.should_see("Dashboard")

    assert store.sign_in("Anna", "nowe-haslo").id == anna.id


async def test_switching_user_returns_to_the_login_screen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    UserStore(tmp_path).create("Anna", "sekret")

    async with user_simulation(main_file=MAIN_FILE) as user:
        await user.open("/")
        _sign_in(user, "sekret")
        await user.should_see("Dashboard")
        user.find(marker="user-menu").click()
        user.find(marker="switch-user").click()
        await user.open("/")

        await user.should_see("Zaloguj się")


def test_failed_move_stops_the_start_with_a_polish_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def locked() -> None:
        raise PermissionError("in use")

    shown: list[str] = []
    monkeypatch.setattr(app, "adopt_legacy_data_dir", locked)
    monkeypatch.setattr(app, "show_startup_error", shown.append)

    with pytest.raises(SystemExit):
        app.main()

    assert len(shown) == 1 and "Zamknij" in shown[0]


async def _open_user_settings(user: User) -> None:
    await user.open("/")
    _sign_in(user, "sekret")
    await user.should_see("Dashboard")
    user.find(marker="user-menu").click()
    user.find(marker="menu-settings").click()
    await user.should_see(marker="user-section")


async def test_renaming_the_user_changes_the_pseudonym_but_not_the_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    anna = UserStore(tmp_path).create("Anna", "sekret")

    async with user_simulation(main_file=MAIN_FILE) as user:
        await _open_user_settings(user)
        user.find(marker="user-pseudonym").clear().type("Anna K.")
        user.find(marker="user-rename").click()
        await user.should_see("Zmieniono pseudonim.")

    [renamed] = UserStore(tmp_path).users()
    assert (renamed.id, renamed.pseudonym) == (anna.id, "Anna K.")


async def test_taken_pseudonym_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    UserStore(tmp_path).create("Anna", "sekret")
    UserStore(tmp_path).create("Ewa", "sekret")

    async with user_simulation(main_file=MAIN_FILE) as user:
        await _open_user_settings(user)
        user.find(marker="user-pseudonym").clear().type("ewa")
        user.find(marker="user-rename").click()

        await user.should_see("już istnieje")


async def test_changing_the_password_needs_the_current_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    UserStore(tmp_path).create("Anna", "sekret")

    async with user_simulation(main_file=MAIN_FILE) as user:
        await _open_user_settings(user)
        user.find(marker="user-password-current").type("zle")
        user.find(marker="user-password-new").type("nowe-haslo")
        user.find(marker="user-password-repeated").type("nowe-haslo")
        user.find(marker="user-password-change").click()
        await user.should_see("Nieprawidłowe hasło")

    assert UserStore(tmp_path).sign_in("Anna", "sekret")


async def test_changing_the_password(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    UserStore(tmp_path).create("Anna", "sekret")

    async with user_simulation(main_file=MAIN_FILE) as user:
        await _open_user_settings(user)
        user.find(marker="user-password-current").type("sekret")
        user.find(marker="user-password-new").type("nowe-haslo")
        user.find(marker="user-password-repeated").type("nowe-haslo")
        user.find(marker="user-password-change").click()
        await user.should_see("Zmieniono hasło.")

    assert UserStore(tmp_path).sign_in("Anna", "nowe-haslo")


async def test_new_password_must_be_repeated_and_long_enough(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    UserStore(tmp_path).create("Anna", "sekret")

    async with user_simulation(main_file=MAIN_FILE) as user:
        await _open_user_settings(user)
        user.find(marker="user-password-current").type("sekret")
        user.find(marker="user-password-new").type("abc")
        user.find(marker="user-password-change").click()
        await user.should_see("co najmniej 4")

    assert UserStore(tmp_path).sign_in("Anna", "sekret")


async def test_deleting_the_user_needs_the_password_and_the_pseudonym(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    anna = UserStore(tmp_path).create("Anna", "sekret")

    async with user_simulation(main_file=MAIN_FILE) as user:
        await _open_user_settings(user)
        user.find(marker="user-delete").click()
        user.find(marker="user-delete-password").type("zle")
        user.find(marker="user-delete-pseudonym").type("anna")
        user.find(marker="user-delete-confirm").click()
        await user.should_see("Nieprawidłowe hasło")

    assert (tmp_path / anna.id).is_dir()
    assert UserStore(tmp_path).users() == [anna]


async def test_deleting_the_user_removes_the_folder_and_returns_to_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FINANCIAL_APP_DATA_DIR", str(tmp_path))
    store = UserStore(tmp_path)
    anna = store.create("Anna", "sekret")
    store.create("Ewa", "inne")

    async with user_simulation(main_file=MAIN_FILE) as user:
        await _open_user_settings(user)
        user.find(marker="user-delete").click()
        user.find(marker="user-delete-password").type("sekret")
        user.find(marker="user-delete-pseudonym").type("Anna")
        user.find(marker="user-delete-confirm").click()
        await user.open("/")

        await user.should_see("Zaloguj się")

    assert [u.pseudonym for u in store.users()] == ["Ewa"]
    assert not (tmp_path / anna.id).exists()
