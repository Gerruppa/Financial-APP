"""The saying of the day (issue #178): a line from Bartosz Walaszek's cartoons on the Dashboard and in the menu.

Only lines found in published collections of the shows' quotes are listed.

"Saying", not "Quote": a Quote is an Instrument's price. A saying stays the whole day, so a redraw does not swap it,
and the menu's is the next one on the list, so the two never repeat each other.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Saying:
    """A line and the work it comes from."""

    text: str
    work: str


AUTHOR = "Bartosz Walaszek"
KAPITAN_BOMBA = "Kapitan Bomba"

SAYINGS = (
    Saying("Czujesz ten zapach? Tak pachnie sto złotych.", KAPITAN_BOMBA),
    Saying("To mały krok dla człowieka, ale dla karła – normalny.", KAPITAN_BOMBA),
    Saying("Średnio, tak średnio bym powiedział.", KAPITAN_BOMBA),
    Saying("Mogą zginąć setki, jeżeli nie dziesiątki osób.", KAPITAN_BOMBA),
    Saying(
        "Jeżeli myślicie, że jestem tak głupi na jakiego wyglądam, to się mylicie. Jestem ciut głupszy.",
        KAPITAN_BOMBA,
    ),
    Saying("Biedakowi zawsze wiatr w oczy i chuj w dupę.", KAPITAN_BOMBA),
)


def saying_of_the_day(day: date, menu: bool = False) -> Saying:
    """The Dashboard's saying shown on ``day``, or with ``menu`` the menu's."""
    return SAYINGS[(day.toordinal() + menu) % len(SAYINGS)]
