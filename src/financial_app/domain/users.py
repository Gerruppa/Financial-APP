"""Users (spec 2.1, ADR-0010): the rules for a pseudonym and a password, and the scrypt hash that locks a User in.

The password is a lock, not encryption: the hash only decides who gets past the login screen."""

import hashlib
import hmac
import secrets
from collections.abc import Iterable

MIN_PASSWORD_LENGTH = 4

PSEUDONYM_REQUIRED = "Podaj pseudonim."
PSEUDONYM_TAKEN = "Użytkownik o takim pseudonimie już istnieje."
PASSWORD_TOO_SHORT = f"Hasło musi mieć co najmniej {MIN_PASSWORD_LENGTH} znaki."
PASSWORDS_DIFFER = "Hasła nie są takie same."
WRONG_PASSWORD = "Nieprawidłowe hasło"

# scrypt's cost; the hash keeps its own so that they can change later
_N, _R, _P = 2**14, 8, 1
_SALT_BYTES = 16


def clean_pseudonym(pseudonym: str) -> str:
    return pseudonym.strip()


def pseudonym_error(pseudonym: str, existing: Iterable[str]) -> str | None:
    """Why ``pseudonym`` cannot name a new User: empty, or taken regardless of case; None when it can."""
    cleaned = clean_pseudonym(pseudonym)
    if not cleaned:
        return PSEUDONYM_REQUIRED
    if cleaned.casefold() in {name.casefold() for name in existing}:
        return PSEUDONYM_TAKEN
    return None


def password_error(password: str, repeated: str | None = None) -> str | None:
    """Why ``password`` (typed again as ``repeated``, when asked) cannot be set; None when it can."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return PASSWORD_TOO_SHORT
    if repeated is not None and password != repeated:
        return PASSWORDS_DIFFER
    return None


def hash_password(password: str) -> str:
    """``scrypt$N$r$p$salt$hash`` (hex), with a fresh random salt."""
    salt = secrets.token_bytes(_SALT_BYTES)
    return _format(_N, _R, _P, salt, _scrypt(password, salt, _N, _R, _P))


def verify_password(password: str, stored: str) -> bool:
    """Whether ``password`` matches ``stored``; a malformed hash matches nothing."""
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = _scrypt(password, bytes.fromhex(salt), int(n), int(r), int(p))
        return hmac.compare_digest(digest, bytes.fromhex(expected))
    except ValueError:
        return False


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=128 * n * r * 2)


def _format(n: int, r: int, p: int, salt: bytes, digest: bytes) -> str:
    return f"scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"
