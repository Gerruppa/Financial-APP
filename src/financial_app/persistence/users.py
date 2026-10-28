"""The list of Users (spec 2.1, ADR-0010): pseudonyms and scrypt hashes in one file of the app-data folder, and each
User's folder beside it, named by a fixed id. The first User created takes over the data from before Users."""

import json
import os
import secrets
import shutil
import time
from dataclasses import dataclass, replace
from pathlib import Path

from financial_app.domain.users import (
    WRONG_PASSWORD,
    clean_pseudonym,
    hash_password,
    password_error,
    pseudonym_error,
    verify_password,
)
from financial_app.persistence.paths import BACKUPS_DIR, DATABASE_FILE, LOG_FILE, USERS_FILE

NO_SUCH_USER = "Nie ma takiego użytkownika."


class UserError(Exception):
    """A refusal with a Polish message for the User."""


@dataclass(frozen=True)
class User:
    id: str
    pseudonym: str
    # None after the hash was removed by hand to reset a forgotten password: the next sign-in sets a new one
    password_hash: str | None = None


# Up to 10 s for a file to be released: on a busy machine 1.5 s was not enough
_DELETE_ATTEMPTS = 20
_DELETE_PAUSE = 0.5

# What lay in the app-data folder before Users, with SQLite's journal files beside the database
_LEGACY_FILES = (DATABASE_FILE, f"{DATABASE_FILE}-wal", f"{DATABASE_FILE}-shm", f"{DATABASE_FILE}-journal", LOG_FILE)


class UserStore:
    """The Users of one app-data folder ``root``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / USERS_FILE

    def users(self) -> list[User]:
        if not self.path.is_file():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [User(u["id"], u["pseudonym"], u.get("password_hash")) for u in data["users"]]

    def folder(self, user: User) -> Path:
        return self.root / user.id

    def create(self, pseudonym: str, password: str) -> User:
        """Add a User; the very first one takes over the data that lay in the app-data folder before Users."""
        users = self.users()
        if error := pseudonym_error(pseudonym, [u.pseudonym for u in users]) or password_error(password):
            raise UserError(error)
        user = User(secrets.token_hex(8), clean_pseudonym(pseudonym), hash_password(password))
        folder = self.folder(user)
        folder.mkdir(parents=True)
        if not users:
            self._adopt_existing_data(folder)
        self._save([*users, user])
        return user

    def sign_in(self, pseudonym: str, password: str) -> User:
        user = self.find(pseudonym)
        self.check_password(user, password)
        return user

    def set_password(self, user: User, password: str) -> User:
        if error := password_error(password):
            raise UserError(error)
        changed = replace(user, password_hash=hash_password(password))
        self._replace(changed)
        return changed

    def rename(self, user: User, pseudonym: str) -> User:
        """Give ``user`` another pseudonym; the id, and so the folder, stays. Only the other Users' pseudonyms count as
        taken, so the case of one's own may change."""
        others = [u.pseudonym for u in self.users() if u.id != user.id]
        if error := pseudonym_error(pseudonym, others):
            raise UserError(error)
        changed = replace(user, pseudonym=clean_pseudonym(pseudonym))
        self._replace(changed)
        return changed

    def change_password(self, user: User, current: str, new: str) -> User:
        self.check_password(user, current)
        return self.set_password(user, new)

    def check_password(self, user: User, password: str) -> None:
        if user.password_hash is None or not verify_password(password, user.password_hash):
            raise UserError(WRONG_PASSWORD)

    def delete(self, user: User, password: str) -> None:
        """Remove ``user`` and their whole folder, backups included. The folder goes first, so a folder that cannot be
        removed (a file still open, tried again for a moment) leaves the User listed."""
        self.check_password(user, password)
        for attempt in range(_DELETE_ATTEMPTS):
            try:
                shutil.rmtree(self.folder(user))
                break
            except FileNotFoundError:
                break
            except OSError as error:
                if attempt == _DELETE_ATTEMPTS - 1:
                    raise UserError(f"Nie udało się usunąć folderu użytkownika: {error}") from error
                # A request of the User who just signed out may still hold a file for a moment
                time.sleep(_DELETE_PAUSE)
        self._save([u for u in self.users() if u.id != user.id])

    def find(self, pseudonym: str) -> User:
        for user in self.users():
            if user.pseudonym.casefold() == clean_pseudonym(pseudonym).casefold():
                return user
        raise UserError(NO_SUCH_USER)

    def _adopt_existing_data(self, folder: Path) -> None:
        for name in (*_LEGACY_FILES, BACKUPS_DIR):
            if (self.root / name).exists():
                shutil.move(self.root / name, folder / name)

    def _replace(self, changed: User) -> None:
        self._save([changed if u.id == changed.id else u for u in self.users()])

    def _save(self, users: list[User]) -> None:
        data = {"users": [{k: v for k, v in vars(u).items() if v is not None} for u in users]}
        # Written aside and renamed over, so an interrupted save never leaves a half-written list
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
