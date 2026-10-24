"""The list of Users (spec 2.1, ADR-0010): pseudonyms and scrypt hashes in one file of the app-data folder, and each
User's folder beside it, named by a fixed id. The first User created takes over the data from before Users."""

import json
import os
import secrets
import shutil
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
        if user.password_hash is None or not verify_password(password, user.password_hash):
            raise UserError(WRONG_PASSWORD)
        return user

    def set_password(self, user: User, password: str) -> User:
        if error := password_error(password):
            raise UserError(error)
        changed = replace(user, password_hash=hash_password(password))
        self._save([changed if u.id == user.id else u for u in self.users()])
        return changed

    def find(self, pseudonym: str) -> User:
        for user in self.users():
            if user.pseudonym.casefold() == clean_pseudonym(pseudonym).casefold():
                return user
        raise UserError(NO_SUCH_USER)

    def _adopt_existing_data(self, folder: Path) -> None:
        for name in (*_LEGACY_FILES, BACKUPS_DIR):
            if (self.root / name).exists():
                shutil.move(self.root / name, folder / name)

    def _save(self, users: list[User]) -> None:
        data = {"users": [{k: v for k, v in vars(u).items() if v is not None} for u in users]}
        # Written aside and renamed over, so an interrupted save never leaves a half-written list
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
