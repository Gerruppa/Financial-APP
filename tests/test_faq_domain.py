"""The Pomoc tab's FAQ (issue #156): its Markdown read into sections and questions, and the search over them."""

import pytest

from financial_app.domain.faq import FaqError, matching, parse_faq

SAMPLE = """\
# Pierwsze kroki

## Od czego zacząć? {#start}
Przejdź do: /ustawienia

Najpierw dodaj **konto**.

Potem transakcje.

## Czym jest Widok? {#widok}

Przełącznik w nagłówku.

# Transakcje

## Jak kupić bitcoina? {#kryptowaluty}
Przejdź do: /transakcje

Dodaj instrument z symbolem BTC-USD i zapisz zakup ułamkowej ilości.
"""


def test_reads_sections_with_their_questions_in_order() -> None:
    faq = parse_faq(SAMPLE)

    assert [section.title for section in faq] == ["Pierwsze kroki", "Transakcje"]
    start, view = faq[0].questions
    assert (start.slug, start.title, start.goto) == ("start", "Od czego zacząć?", "/ustawienia")
    assert start.answer == "Najpierw dodaj **konto**.\n\nPotem transakcje."
    assert (view.slug, view.goto) == ("widok", None)
    assert faq[1].questions[0].slug == "kryptowaluty"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("## Pytanie? {#a}\n\nOdpowiedź.\n", "przed pierwszą sekcją"),
        ("# Sekcja\n\n## Pytanie bez slugu?\n\nOdpowiedź.\n", "Pytanie bez slugu?"),
        ("# Sekcja\n\n## Pytanie? {#a}\nPrzejdź do: /x\n\n", "pustą odpowiedź"),
        ("# Sekcja\n\n## Pytanie? {#a}\n\nJedno.\n\n## Drugie? {#a}\n\nDwa.\n", "#a"),
        ("# Pusta\n\n# Sekcja\n\n## Pytanie? {#a}\n\nOdpowiedź.\n", "Pusta"),
        ("Tekst bez sekcji.\n", "przed pierwszą sekcją"),
    ],
)
def test_refuses_an_entry_without_a_title_slug_or_answer(text: str, message: str) -> None:
    with pytest.raises(FaqError, match=message):
        parse_faq(text)


@pytest.mark.parametrize(
    ("query", "slugs"),
    [
        ("", ["start", "widok", "kryptowaluty"]),
        ("bitcoin", ["kryptowaluty"]),
        ("BTC-usd", ["kryptowaluty"]),
        ("  zaczac ", ["start"]),  # without the Polish letters
        ("ułamkowej", ["kryptowaluty"]),
        ("przełącznik", ["widok"]),  # in the answer
        ("lokata", []),
    ],
)
def test_search_keeps_the_questions_whose_title_or_answer_contains_the_text(query: str, slugs: list[str]) -> None:
    faq = parse_faq(SAMPLE)

    assert [question.slug for question in matching(faq, query)] == slugs
