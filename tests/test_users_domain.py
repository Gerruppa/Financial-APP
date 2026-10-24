from financial_app.domain.users import (
    PASSWORD_TOO_SHORT,
    PASSWORDS_DIFFER,
    PSEUDONYM_REQUIRED,
    PSEUDONYM_TAKEN,
    hash_password,
    password_error,
    pseudonym_error,
    verify_password,
)


def test_pseudonym_is_required() -> None:
    assert pseudonym_error("   ", []) == PSEUDONYM_REQUIRED


def test_pseudonym_is_unique_regardless_of_case() -> None:
    assert pseudonym_error(" anna ", ["Anna"]) == PSEUDONYM_TAKEN
    assert pseudonym_error("Ania", ["Anna"]) is None


def test_password_needs_four_characters() -> None:
    assert password_error("abc") == PASSWORD_TOO_SHORT
    assert password_error("abcd") is None


def test_password_must_be_repeated_alike() -> None:
    assert password_error("abcd", "abce") == PASSWORDS_DIFFER
    assert password_error("abcd", "abcd") is None


def test_hash_verifies_only_its_password() -> None:
    stored = hash_password("sekret")

    assert verify_password("sekret", stored)
    assert not verify_password("Sekret", stored)


def test_hashes_of_one_password_differ_by_salt() -> None:
    assert hash_password("sekret") != hash_password("sekret")


def test_malformed_hash_matches_nothing() -> None:
    assert not verify_password("sekret", "")
    assert not verify_password("sekret", "scrypt$x$y")
