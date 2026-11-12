"""Stages: the checks in the order to fix their problems.

Problems of an earlier stage cause false problems in the later ones (a wrong Wordlist entry makes spelling
problems, a misspelled word is also missing from the word breaks list), so the window and the reports show the
checks stage by stage. Every check is in exactly one stage (a test makes sure of it).
"""
from __future__ import annotations

from collections.abc import Iterable

STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Unit 1. Project settings and lists", ("lists", "approvals", "term-lists", "term-renderings")),
    ("Unit 2. File structure",
     ("usfm", "book-titles", "glossary-words", "figures", "untranslated-verses", "repeated-text", "verse-lengths",
      "normalization", "special-spaces")),
    ("Unit 3. Characters and punctuation",
     ("characters", "scripts", "apostrophes", "punctuation", "paragraph-final", "dashes", "ellipses", "quotes", "pairs",
      "spacing", "numbers", "digit-systems", "fractions")),
    ("Unit 4. Words",
     ("spelling", "hyphenation", "mixed-capitalization", "capitalization", "heading-case", "repeated-words",
      "ordinals")),
    ("Unit 5. References and terms",
     ("references", "self-references", "one-chapter-books", "book-name-forms", "footnotes", "footnote-quotes",
      "note-callers", "terms",
      "parallel-changes", "parallel-differences")),
    ("Unit 6. Review lists", ("variants", "name-case", "styled-words", "divine-name",
                             "poetry-numbers", "line-ends", "poetry-two-sentences", "poetry-long-lines",
                             "poetry-verse-inside", "poetry-chapter-break", "unused")),
)
# Groups inside a unit (unit number, title, checks in the order to fix their problems): the window shows them
# folded, the reports under their own heading. Their checks are also in STAGES, next to each other.
GROUPS: tuple[tuple[int, str, tuple[str, ...]], ...] = (
    (1, "Wordlist and inventories", ("lists", "approvals")),
    (1, "Biblical terms lists", ("term-lists", "term-renderings")),
    (2, "Markers and titles", ("usfm", "book-titles", "glossary-words", "figures")),
    (2, "Verse text", ("untranslated-verses", "repeated-text", "verse-lengths")),
    (2, "Invisible characters", ("normalization", "special-spaces")),
    (3, "Characters", ("characters", "scripts", "apostrophes")),
    (3, "Punctuation", ("punctuation", "paragraph-final", "dashes", "ellipses")),
    (3, "Quotes and brackets", ("quotes", "pairs")),
    (3, "Numbers and spaces", ("spacing", "numbers", "digit-systems", "fractions")),
    (4, "Spelling and word breaks", ("spelling", "hyphenation")),
    (4, "Capital letters", ("mixed-capitalization", "capitalization", "heading-case")),
    (5, "References", ("references", "self-references", "one-chapter-books", "book-name-forms")),
    (5, "Footnotes", ("footnotes", "footnote-quotes", "note-callers")),
    (5, "Parallel passages", ("parallel-changes", "parallel-differences")),
    (6, "Names", ("variants", "name-case")),
    (6, "Divine name and styles", ("styled-words", "divine-name")),
    (6, "Poetry and lists", ("poetry-numbers", "line-ends", "poetry-two-sentences", "poetry-long-lines",
                   "poetry-verse-inside", "poetry-chapter-break")),
)

# Stages whose errors are named at the top of the report: fix them before the others.
FIRST_STAGES = 2


def group_of(check: str) -> str:
    """Title of the group of `check`; "" = in no group."""
    return next((title for _, title, checks in GROUPS if check in checks), "")


def stage_number(check: str) -> int:
    """1-based number of the stage of `check`; 0 = in no stage."""
    return next((number for number, (_, checks) in enumerate(STAGES, start=1) if check in checks), 0)


def in_stage_order(checks: Iterable[str]) -> list[str]:
    """`checks` sorted by stage, in the order of STAGES; checks in no stage at the end."""
    order = {name: index for index, name in enumerate(name for _, names in STAGES for name in names)}
    return sorted(dict.fromkeys(checks), key=lambda name: order.get(name, len(order)))


def stage_checks(numbers: Iterable[int]) -> list[str]:
    """The checks of the given stages (1-based), in stage order."""
    wanted = set(numbers)
    return [name for number, (_, names) in enumerate(STAGES, start=1) if number in wanted for name in names]
