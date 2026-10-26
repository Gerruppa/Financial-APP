"""The command palette inside the header search: commands (go to a tab, add a Transaction, switch the Theme, ...) listed
while typing, found by the start of a word of their label or keywords.

A command here is only its name and what finds it; what it does belongs to the UI (``ui/header_search.py``).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from financial_app.domain.formatting import folded

# A query starting with this lists commands only, however short (as in a code editor's palette)
COMMAND_PREFIX = ">"
# Outside command mode: the shortest query that finds commands, and how many the list shows
COMMAND_MIN_QUERY = 2
COMMAND_LIMIT = 6


@dataclass(frozen=True)
class Command:
    """``key`` names it for the UI, ``label`` is what the user reads (Polish), ``keywords`` other words that find it."""

    key: str
    label: str
    keywords: tuple[str, ...] = ()


def in_command_mode(query: str) -> bool:
    """Whether ``query`` starts with the command prefix."""
    return query.strip().startswith(COMMAND_PREFIX)


def matching_commands(commands: Sequence[Command], query: str) -> list[Command]:
    """The ``commands`` in which every word of ``query`` starts a word of the label or a keyword, ignoring case and
    Polish letters, in their order. A query of fewer than ``COMMAND_MIN_QUERY`` characters finds none and the list is
    cut at ``COMMAND_LIMIT``; after the ``COMMAND_PREFIX`` there is no minimum and no cut (a bare prefix lists all)."""
    text = query.strip()
    command_mode = in_command_mode(text)
    if command_mode:
        text = text.removeprefix(COMMAND_PREFIX)
    wanted = folded(text).split()
    if not command_mode and len(" ".join(wanted)) < COMMAND_MIN_QUERY:
        return []
    found = [command for command in commands if _matches(command, wanted)]
    return found if command_mode else found[:COMMAND_LIMIT]


def _matches(command: Command, wanted: list[str]) -> bool:
    words = folded(" ".join([command.label, *command.keywords])).replace(":", " ").split()
    return all(any(word.startswith(part) for word in words) for part in wanted)
