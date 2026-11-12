"""Poetry checks (Unit 6, group Poetry): lines of \\q, \\q1, \\q2 … found by the text, never changed.

- poetry-numbers: a number written with digits (any digits: 0-9 and those of other scripts) in a poetry line.
  Poetry usually writes numbers in words. References (12:5) and \\xt are not counted; \\qr (a reference under a
  poem), \\qa (acrostic headings) and \\qd are not poetry lines.
- poetry-two-sentences: a long poetry line (longer than 95% of the poetry lines of the project) with a sentence end
  inside it: maybe it should be two lines. Only full stops, exclamation and question marks count (by Unicode name),
  not commas, semicolons or colons, even if SentenceFinalPunctuation lists them. Two short sentences in one line
  ("Hear this, you kings! Listen, you rulers!") are normal poetry and are not long. Words of the speaker after a
  quote (a dash or a small letter after the mark: "…Me? — says the LORD") do not start a new sentence.
Front/back matter and extra material (XXA…) are not checked: they use \\q for study notes.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator

from checker.model import WARNING, Analysis, CheckContext, Finding
from checker.structure import PERIPHERAL_BOOKS

POETRY_STYLE_RE = re.compile(r"(q\d*|qm\d*|qc)$")
NUMBER_STYLES = frozenset({"xt", "fig"})  # numbers inside these character styles are references or not text
MIN_LINES = 100  # fewer poetry lines: no reliable "long" for the project
LONG_SHARE = 0.95  # a line is long when it is longer than this part of the poetry lines
MIN_LONG = 40  # characters: never call a shorter line long
MIN_SIDE = 20  # characters of text on each side of the sentence end
SENTENCE_END_NAMES = ("FULL STOP", "EXCLAMATION MARK", "QUESTION MARK", "DANDA")
CLOSING_QUOTE_CATEGORIES = frozenset({"Pf", "Pe"})


def is_poetry_line(analysis: Analysis) -> bool:
    """Scripture poetry: front/back matter and extra material use \\q for other things (study notes)."""
    segment = analysis.segment
    return (not segment.in_note and bool(POETRY_STYLE_RE.match(segment.style))
            and segment.book not in PERIPHERAL_BOOKS)


def check_poetry_numbers(lines: list[Analysis], ctx: CheckContext) -> Iterator[Finding]:
    separator = re.escape(ctx.settings.chapter_verse_separator or ":")
    # A number with its separators (40,000; 1.5); with the chapter-verse mark it is a reference (40:8).
    number_re = re.compile(rf"\d+(?:[^\w\s]\d+)*")
    for analysis in lines:
        text = analysis.segment.text
        for match in number_re.finditer(text):
            # 40:8 is a reference, 7–8 a verse range
            if re.search(separator, match.group()) or any(unicodedata.category(ch) == "Pd" for ch in match.group()):
                continue
            if analysis.segment.styles_at(match.start()) & NUMBER_STYLES:
                continue
            number = match.group()
            yield analysis.finding(match.start(), len(number), WARNING, "poetry-numbers", number,
                                   f"number '{number}' is written with digits in a poetry line "
                                   f"(\\{analysis.segment.style}). Poetry usually writes numbers in words")


def _sentence_end_marks(ctx: CheckContext) -> frozenset[str]:
    marks = set("".join(ctx.settings.sentence_final_punctuation)) or set(".!?")
    return frozenset(ch for ch in marks if any(name in unicodedata.name(ch, "") for name in SENTENCE_END_NAMES))


def long_line_limit(lines: list[Analysis]) -> int | None:
    """Length that 95% of the poetry lines do not pass; None when there are too few lines."""
    lengths = sorted(len(analysis.segment.text.strip()) for analysis in lines)
    if len(lengths) < MIN_LINES:
        return None
    return max(lengths[int(len(lengths) * LONG_SHARE) - 1], MIN_LONG)


def _sentence_end(text: str, marks: frozenset[str], ctx: CheckContext) -> int | None:
    """Offset just after the first sentence end inside `text` with enough text on both sides; else None."""
    start = len(text) - len(text.lstrip())
    end = len(text.rstrip())
    for index in range(start + MIN_SIDE, end - MIN_SIDE):
        if text[index] not in marks or not text[index - 1].isalpha():
            continue
        after = index + 1
        while after < end and (text[after] in marks or unicodedata.category(text[after]) in CLOSING_QUOTE_CATEGORIES):
            after += 1
        if after >= end or not text[after].isspace() or end - after < MIN_SIDE:
            continue
        # Not a new sentence: words of the speaker after a quote ("…Me? — says the LORD", "…?” he said).
        rest = text[after:].lstrip()
        if unicodedata.category(rest[0]) == "Pd":
            continue
        letter = next((ch for ch in rest if ch.isalpha()), "")
        if letter.islower():
            continue
        word = re.search(r"\w+$", text[:index])
        if word and f"{word.group()}{text[index]}".lower() in ctx.abbreviations:
            continue
        return after
    return None


def check_poetry_two_sentences(lines: list[Analysis], ctx: CheckContext) -> Iterator[Finding]:
    limit = long_line_limit(lines)
    marks = _sentence_end_marks(ctx)
    if limit is None or not marks:
        return
    for analysis in lines:
        text = analysis.segment.text
        length = len(text.strip())
        if length <= limit:
            continue
        after = _sentence_end(text, marks, ctx)
        if after is None:
            continue
        words = text[:after].split()
        end = " ".join(words[-2:])
        yield analysis.finding(after - 1, 1, WARNING, "poetry-two-sentences", end,
                               f"long poetry line ({length} characters; 95% of the poetry lines are not longer than "
                               f"{limit}) has two sentences: maybe start a new line after '{end}'")
