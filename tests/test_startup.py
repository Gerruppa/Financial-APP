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
