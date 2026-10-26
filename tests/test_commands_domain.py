"""The command palette's matching (the header search's "Polecenia"): which commands a query finds."""

from financial_app.domain.commands import (
    COMMAND_LIMIT,
    Command,
    in_command_mode,
    matching_commands,
)

COMMANDS = [
    Command("go-portfolio", "Przejdź do: Portfolio"),
    Command("go-bonds", "Przejdź do: Dochód stały", ("obligacje", "lokaty")),
    Command("add", "Dodaj transakcję", ("zakup", "wpłata")),
    Command("theme", "Przełącz motyw", ("golden", "jasny")),
    Command("discreet", "Tryb dyskrecji: ukryj lub pokaż kwoty"),
]


def keys(query: str) -> list[str]:
    return [command.key for command in matching_commands(COMMANDS, query)]


def test_a_query_matches_the_start_of_a_word_of_the_label() -> None:
    assert keys("port") == ["go-portfolio"]
    assert keys("dysk") == ["discreet"]


def test_it_matches_keywords_and_ignores_case_and_polish_letters() -> None:
    assert keys("OBLIG") == ["go-bonds"]
    assert keys("przelacz") == ["theme"]
    assert keys("wplata") == ["add"]


def test_every_word_of_the_query_must_match() -> None:
    assert keys("przejdz doch") == ["go-bonds"]
    assert keys("przejdz xyz") == []


def test_a_word_is_matched_from_its_start_not_from_the_middle() -> None:
    assert keys("folio") == []


def test_a_one_letter_query_finds_nothing() -> None:
    assert keys("p") == []
    assert keys("") == []


def test_the_prefix_lists_every_command_and_filters_by_the_rest() -> None:
    assert in_command_mode(">") and in_command_mode("  > tryb")
    assert not in_command_mode("pzu")
    assert keys(">") == [command.key for command in COMMANDS]
    assert keys("> tryb") == ["discreet"]
    assert keys(">t") == ["add", "discreet"]  # "transakcję" and "Tryb"; a single letter is enough after the prefix


def test_the_list_is_cut_at_the_limit_except_in_command_mode() -> None:
    many = [Command(f"c{i}", f"Polecenie {i}") for i in range(COMMAND_LIMIT + 3)]

    assert len(matching_commands(many, "polecenie")) == COMMAND_LIMIT
    assert len(matching_commands(many, ">polecenie")) == len(many)
