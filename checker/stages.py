"""Stages: the checks in the order to fix their problems.

Problems of an earlier stage cause false problems in the later ones (a wrong Wordlist entry makes spelling
problems, a misspelled word is also missing from the word breaks list), so the window and the reports show the
checks stage by stage. Every check is in exactly one stage (a test makes sure of it).
"""
from __future__ import annotations

from collections.abc import Iterable

STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Unit 1. Project settings and lists", ("lists", "approvals", "term-lists")),
    ("Unit 2. File structure", ("usfm", "book-titles", "normalization", "special-spaces")),
    ("Unit 3. Characters and punctuation",
     ("characters", "scripts", "punctuation", "spacing", "numbers", "quotes", "pairs", "paragraph-final")),
    ("Unit 4. Words",
     ("spelling", "mixed-capitalization", "capitalization", "repeated-words", "ordinals", "hyphenation")),
    ("Unit 5. References and terms",
     ("references", "footnotes", "terms", "parallel-changes", "parallel-differences")),
    ("Unit 6. Review lists", ("variants", "name-case", "styled-words", "divine-name", "unused")),
)
# Stages whose errors are named at the top of the report: fix them before the others.
FIRST_STAGES = 2


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
