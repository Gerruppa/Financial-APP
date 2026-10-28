import json
import shutil
import threading
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


def test_rename_keeps_the_id_and_the_folder(store: UserStore, tmp_path: Path) -> None:
    anna = store.create("Anna", "sekret")
    (store.folder(anna) / DATABASE_FILE).write_text("db")

    renamed = store.rename(anna, "  Anna K.  ")

    assert renamed.id == anna.id
    assert [u.pseudonym for u in UserStore(tmp_path).users()] == ["Anna K."]
    assert (store.folder(renamed) / DATABASE_FILE).read_text() == "db"
    assert store.sign_in("anna k.", "sekret").id == anna.id


def test_rename_may_change_only_the_case_of_the_own_pseudonym(store: UserStore) -> None:
    anna = store.create("Anna", "sekret")

    assert store.rename(anna, "ANNA").pseudonym == "ANNA"


def test_rename_to_the_pseudonym_of_another_user_is_refused(store: UserStore) -> None:
    anna = store.create("Anna", "sekret")
    store.create("Ewa", "sekret")

    with pytest.raises(UserError):
        store.rename(anna, "ewa")
    assert [u.pseudonym for u in store.users()] == ["Anna", "Ewa"]


def test_rename_to_an_empty_pseudonym_is_refused(store: UserStore) -> None:
    anna = store.create("Anna", "sekret")

    with pytest.raises(UserError):
        store.rename(anna, "   ")


def test_change_password_needs_the_current_one(store: UserStore) -> None:
    anna = store.create("Anna", "sekret")

    with pytest.raises(UserError, match=WRONG_PASSWORD):
        store.change_password(anna, "zle", "nowe-haslo")
    assert store.sign_in("Anna", "sekret").id == anna.id


def test_change_password_sets_the_new_one(store: UserStore) -> None:
    anna = store.create("Anna", "sekret")

    changed = store.change_password(anna, "sekret", "nowe-haslo")

    assert store.sign_in("Anna", "nowe-haslo") == changed
    with pytest.raises(UserError):
        store.sign_in("Anna", "sekret")


def test_change_password_refuses_a_short_new_one(store: UserStore) -> None:
    anna = store.create("Anna", "sekret")

    with pytest.raises(UserError):
        store.change_password(anna, "sekret", "abc")
    assert store.sign_in("Anna", "sekret").id == anna.id


def test_delete_removes_the_user_and_the_whole_folder(store: UserStore) -> None:
    anna = store.create("Anna", "sekret")
    ewa = store.create("Ewa", "sekret")
    (store.folder(anna) / BACKUPS_DIR).mkdir()
    (store.folder(anna) / BACKUPS_DIR / "copy.sqlite3").write_text("backup")

    store.delete(anna, "sekret")

    assert [u.pseudonym for u in store.users()] == ["Ewa"]
    assert not store.folder(anna).exists()
    assert store.folder(ewa).is_dir()


def test_delete_needs_the_password(store: UserStore) -> None:
    anna = store.create("Anna", "sekret")

    with pytest.raises(UserError, match=WRONG_PASSWORD):
        store.delete(anna, "zle")
    assert store.users() == [anna]
    assert store.folder(anna).is_dir()


def test_failed_delete_keeps_the_user_listed(store: UserStore, monkeypatch: pytest.MonkeyPatch) -> None:
    anna = store.create("Anna", "sekret")

    def locked(path: Path) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr("financial_app.persistence.users.shutil.rmtree", locked)
    monkeypatch.setattr("financial_app.persistence.users.time.sleep", lambda seconds: None)

    with pytest.raises(UserError):
        store.delete(anna, "sekret")
    assert store.users() == [anna]


def test_delete_tries_again_while_a_file_is_still_held(store: UserStore, monkeypatch: pytest.MonkeyPatch) -> None:
    anna = store.create("Anna", "sekret")
    real_rmtree = shutil.rmtree
    calls: list[Path] = []

    def held_once(path: Path) -> None:
        calls.append(path)
        if len(calls) == 1:
            raise PermissionError("in use")
        real_rmtree(path)

    monkeypatch.setattr("financial_app.persistence.users.shutil.rmtree", held_once)
    monkeypatch.setattr("financial_app.persistence.users.time.sleep", lambda seconds: None)

    store.delete(anna, "sekret")

    assert len(calls) == 2
    assert store.users() == []


def test_delete_waits_for_a_file_that_a_slow_machine_releases_late(store: UserStore) -> None:
    anna = store.create("Anna", "sekret")
    held = (store.folder(anna) / "held.log").open("w")
    # Windows refuses to delete a folder with an open file; on a busy machine the release can take a few seconds
    release = threading.Timer(2.0, held.close)
    release.start()
    try:
        store.delete(anna, "sekret")
    finally:
        release.join()

    assert store.users() == []
    assert not store.folder(anna).exists()
