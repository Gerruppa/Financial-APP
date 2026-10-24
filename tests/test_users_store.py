import json
from pathlib import Path

import pytest

from financial_app.domain.users import WRONG_PASSWORD
from financial_app.persistence.paths import BACKUPS_DIR, DATABASE_FILE, LOG_FILE
from financial_app.persistence.users import UserError, UserStore


@pytest.fixture
def store(tmp_path: Path) -> UserStore:
    return UserStore(tmp_path)


def test_no_users_at_first(store: UserStore) -> None:
    assert store.users() == []


def test_created_user_is_listed_and_has_a_folder_of_a_fixed_id(store: UserStore, tmp_path: Path) -> None:
    user = store.create("Anna", "sekret")

    assert [u.pseudonym for u in store.users()] == ["Anna"]
    assert store.folder(user) == tmp_path / user.id
    assert store.folder(user).is_dir()
    # A new store reads the same list back
    assert UserStore(tmp_path).users()[0].id == user.id


def test_list_holds_a_hash_not_the_password(store: UserStore, tmp_path: Path) -> None:
    store.create("Anna", "sekret")

    assert "sekret" not in (tmp_path / "users.json").read_text(encoding="utf-8")


def test_pseudonym_must_be_unique_regardless_of_case(store: UserStore) -> None:
    store.create("Anna", "sekret")

    with pytest.raises(UserError):
        store.create("anna", "inne-haslo")


def test_short_password_is_refused(store: UserStore) -> None:
    with pytest.raises(UserError):
        store.create("Anna", "abc")
    assert store.users() == []


def test_sign_in_with_the_right_password(store: UserStore) -> None:
    created = store.create("Anna", "sekret")

    assert store.sign_in("anna", "sekret") == created


def test_wrong_password_says_so(store: UserStore) -> None:
    store.create("Anna", "sekret")

    with pytest.raises(UserError, match=WRONG_PASSWORD):
        store.sign_in("Anna", "zle")


def test_removing_the_hash_resets_the_password_at_the_next_sign_in(store: UserStore, tmp_path: Path) -> None:
    store.create("Anna", "sekret")
    path = tmp_path / "users.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["users"][0]["password_hash"]
    path.write_text(json.dumps(data), encoding="utf-8")

    anna = UserStore(tmp_path).users()[0]
    assert anna.password_hash is None
    store.set_password(anna, "nowe-haslo")
    assert UserStore(tmp_path).sign_in("Anna", "nowe-haslo").pseudonym == "Anna"


def test_first_user_takes_over_the_existing_data(store: UserStore, tmp_path: Path) -> None:
    (tmp_path / DATABASE_FILE).write_text("db")
    (tmp_path / LOG_FILE).write_text("log")
    (tmp_path / BACKUPS_DIR).mkdir()
    (tmp_path / BACKUPS_DIR / "copy.sqlite3").write_text("backup")

    anna = store.create("Anna", "sekret")

    folder = store.folder(anna)
    assert (folder / DATABASE_FILE).read_text() == "db"
    assert (folder / LOG_FILE).read_text() == "log"
    assert (folder / BACKUPS_DIR / "copy.sqlite3").read_text() == "backup"
    assert not (tmp_path / DATABASE_FILE).exists()
    assert not (tmp_path / BACKUPS_DIR).exists()


def test_second_user_gets_an_empty_folder(store: UserStore, tmp_path: Path) -> None:
    store.create("Anna", "sekret")
    (tmp_path / DATABASE_FILE).write_text("db")

    ewa = store.create("Ewa", "sekret")

    assert not (store.folder(ewa) / DATABASE_FILE).exists()
    assert (tmp_path / DATABASE_FILE).exists()
