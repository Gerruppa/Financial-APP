"""GLOSSARY.md, the Polish-to-English index of CONTEXT.md, lists exactly the terms CONTEXT.md defines."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# A defined term: "**Fund Code** (Kod funduszu):", or "**XIRR**:" when the UI uses the English name too
TERM = re.compile(r"^\*\*(?P<english>[^*]+)\*\*(?: \((?P<polish>[^)]+)\))?:", re.MULTILINE)
ROW = re.compile(r"^\| (?P<polish>[^|]+?) \| \[(?P<english>[^\]]+)\]\(CONTEXT\.md#[a-z0-9-]+\) \|", re.MULTILINE)


def test_the_glossary_indexes_every_term_of_context_md() -> None:
    context = (ROOT / "CONTEXT.md").read_text(encoding="utf-8")
    glossary = (ROOT / "GLOSSARY.md").read_text(encoding="utf-8")

    defined = {(m["polish"] or m["english"], m["english"]) for m in TERM.finditer(context)}
    indexed = [(m["polish"], m["english"]) for m in ROW.finditer(glossary)]

    assert len(defined) == 44
    assert sorted(indexed) == sorted(defined), "GLOSSARY.md differs from the terms of CONTEXT.md"
    assert len(indexed) == len(set(indexed))
