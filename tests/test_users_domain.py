from financial_app.domain.users import (
    AVATAR_COLOURS,
    PASSWORD_TOO_SHORT,
    PASSWORDS_DIFFER,
    PSEUDONYM_REQUIRED,
    PSEUDONYM_TAKEN,
    avatar_colour,
    hash_password,
    initials,
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


def test_initials_are_the_first_letters_of_the_first_two_words() -> None:
    assert initials("Jan Kowalski") == "JK"
    assert initials("  jan   maria kowalski ") == "JM"


def test_initials_of_one_word_are_its_first_two_letters() -> None:
    assert initials("gerruppa") == "GE"
    assert initials("Ł") == "Ł"


def test_avatar_colour_is_stable_and_from_the_palette() -> None:
    assert avatar_colour("Anna") == avatar_colour("Anna")
    assert avatar_colour("Anna") in AVATAR_COLOURS
    assert len({avatar_colour(name) for name in ["Anna", "Jan", "Ola", "Piotr", "Zofia", "Marek"]}) > 1
