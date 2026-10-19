"""The saying of the day (issue #178): a line from Bartosz Walaszek's cartoons (Kapitan Bomba, Egzorcysta) or
Chłopaki z baraków at the foot of the menu.

"Saying", not "Quote": a Quote is an Instrument's price. A saying stays the whole day, so a redraw does not swap it.
Only lines found in published
collections of the shows' quotes are listed.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Saying:
    """A line, the work it comes from and the work's author, ``None`` when the signature names the work alone."""

    text: str
    work: str
    author: str | None = None


WALASZEK = "Bartosz Walaszek"
KAPITAN_BOMBA = "Kapitan Bomba"
EGZORCYSTA = "Egzorcysta"
BOGDAN_BONER = "Bogdan Boner: Egzorcysta"
CHLOPAKI_Z_BARAKOW = "Chłopaki z baraków"


def _bomba(text: str) -> Saying:
    return Saying(text, KAPITAN_BOMBA, WALASZEK)


def _egzorcysta(text: str) -> Saying:
    return Saying(text, EGZORCYSTA, WALASZEK)


def _boner(text: str) -> Saying:
    return Saying(text, BOGDAN_BONER, WALASZEK)


def _baraki(text: str) -> Saying:
    return Saying(text, CHLOPAKI_Z_BARAKOW)


# The works take turns from day to day
SAYINGS = (
    _bomba("Czujesz ten zapach? Tak pachnie sto złotych."),
    _egzorcysta(
        "Marcinek, nie słyszałeś, że pieniądze szczęścia nie dają? Jak ci dam, to wydasz. A jak ci nie dam, to nie "
        "wydasz. Widzisz jaka oszczędność?"
    ),
    _baraki("Zauważyłem, że jak coś się wrzuci do jeziora albo do morza to następnego dnia już tego nie ma."),
    _egzorcysta(
        "To nie ważne kim jestem. Ważne jest to, co robię. A robię niewiele. Tyle żeby zarobić, a się nie narobić."
    ),
    _bomba("To mały krok dla człowieka, ale dla karła – normalny."),
    _egzorcysta("Uczysz się. Powoli i opornie, ale zawsze."),
    _baraki("Dlaczego pozwoliłeś, żeby się wszystko pojebało? Wiedziałeś, że jestem głupi."),
    _boner("Szkoda, że ostatnio zleceń mamy tyle, co Domino rozumu."),
    _bomba("Średnio, tak średnio bym powiedział."),
    _egzorcysta("Należy się dwieście. No z fakturą by było jeszcze drożej."),
    _baraki("Jakbyś miał jakiś problem, to broń Boże nie dzwoń, bo ja się niczym nie będę zajmował."),
    _egzorcysta("Zdarza się nawet najlepszym, a że jestem najlepszy, to zdarza mi się ciągle."),
    _bomba("Mogą zginąć setki, jeżeli nie dziesiątki osób."),
    _egzorcysta(
        "Ehh, Marcinek, Marcinek. Gdybyś ty jeszcze tak samo się do łopaty rwał, to byśmy już milionerami byli."
    ),
    _baraki("Napijesz się, naćpasz, a wypadek i tak by się zdarzył."),
    _boner("Marcinek, nie płacą nam za pierdolenie, tylko za zapierdolenie diabła."),
    _bomba("Jeżeli myślicie, że jestem tak głupi na jakiego wyglądam, to się mylicie. Jestem ciut głupszy."),
    _egzorcysta("Twoja strata, moje zdrowie."),
    _baraki("Mam kaca, ale staram się być dobrym ojcem."),
    _egzorcysta(
        "Jak bym zainwestował w kosiarkę z koszem, to już byś mi nie był potrzebny, i musiałbym Cię zwolnić. Ale nie "
        "martw się, nie zrobię tego. Jesteś tańszy niż kosiareczka z koszem."
    ),
    _bomba("Biedakowi zawsze wiatr w oczy i chuj w dupę."),
    _egzorcysta("Gdyby ludzie przejmowali się tym, co mówią lekarze, to gorzelnie by splajtowały."),
    _baraki("Cyrus nie jest stąd, czujecie? Tutaj wszyscy za wszystkich i jeden za jednego."),
    _egzorcysta("Darowanej flaszce w objętość się nie zagląda."),
    _baraki("Randy... To ja jestem wódką."),
    _egzorcysta("Piwo nie ma nóg, i samo do mnie ze sklepu nie przywędruje."),
    _baraki("Jak niby orzeszki mogą zabić? Przecież to nie są nawet ludzie."),
)


def saying_of_the_day(day: date) -> Saying:
    """The saying shown on ``day``."""
    return SAYINGS[day.toordinal() % len(SAYINGS)]
