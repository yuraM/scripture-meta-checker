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
from checker.usfm import Segment

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


# --- checks that look at neighbouring paragraphs (UsageCounter.flow: paragraphs and headings, no notes) ---

LEAD_IN_STYLE_RE = re.compile(r"(p|m|pi\d*|pm\w*|mi|nb|pc)$")
LINE_END_NAMES = ("COMMA", "SEMICOLON")


def is_poetry_segment(segment: Segment) -> bool:
    return (not segment.in_note and bool(POETRY_STYLE_RE.match(segment.style))
            and segment.book not in PERIPHERAL_BOOKS)


def _chapter(segment: Segment) -> str:
    return segment.anchors[0][1] if segment.anchors else ""


def _finding(segment: Segment, offset: int, length: int, check: str, item: str, message: str) -> Finding:
    return Analysis(segment, [], []).finding(offset, length, WARNING, check, item, message)


def _last_mark(text: str) -> tuple[str, int]:
    """The last sign of `text` before closing quotes, and its offset; "" = it ends with a word or a number."""
    index = len(text.rstrip()) - 1
    while index >= 0 and unicodedata.category(text[index]) in CLOSING_QUOTE_CATEGORIES:
        index -= 1
    if index < 0 or text[index].isalnum():
        return "", max(index, 0)
    return text[index], index


def _pairs(flow: list[Segment]) -> Iterator[tuple[Segment, Segment]]:
    """Neighbouring paragraphs of one book."""
    for first, second in zip(flow, flow[1:]):
        if first.book == second.book and first.book not in PERIPHERAL_BOOKS:
            yield first, second


def _named(ch: str, names: tuple[str, ...]) -> bool:
    return any(name in unicodedata.name(ch, "") for name in names)


LONG_LINE_SHARE = 0.99  # a very long line is longer than 99% of the poetry lines
LONG_LINE_TIMES = 2.5  # and this many times longer than the usual (median) line
MIN_LOWERCASE = 3  # the word is written small at least this often elsewhere (and never capitalized mid-sentence)
MAX_CAPITAL_SHARE = 0.1  # more capitals after a line-end comma: the project starts every line with a capital
MIN_LINE_STARTS = 20  # the share is known only from this many line starts after a comma


def check_poetry_line_ends(flow: list[Segment], case_refs: dict, ctx: CheckContext) -> Iterator[Finding]:
    """A line ends with a comma or semicolon, the next line starts with a capital, and that word is written small
    everywhere else in the middle of a sentence: a full stop is missing, or the capital is wrong. A project that
    starts many such lines with a capital (more than 10%) does it on purpose: nothing is listed, a note says so."""
    found: list[Finding] = []
    small = 0
    for first, second in _pairs(flow):
        if not (is_poetry_segment(first) and is_poetry_segment(second)) or second.previous_style != first.style:
            continue
        mark, _ = _last_mark(first.text)
        if not mark or not _named(mark, LINE_END_NAMES):
            continue
        start = len(second.text) - len(second.text.lstrip())
        word = re.match(r"\w+", second.text[start:])
        if not word or word.group().isupper():
            continue
        capitalized, lowercase = case_refs.get(word.group().lower(), ([], []))
        if capitalized or len(lowercase) < MIN_LOWERCASE:
            continue
        if not word.group()[0].isupper():
            small += 1
            continue
        found.append(_finding(second, start, len(word.group()), "poetry-line-ends", word.group(),
                       f"the line before ends with '{mark}', but this line starts with '{word.group()}', which is "
                       f"written small everywhere else ({len(lowercase)}×): a full stop is missing, or write "
                       f"'{word.group().lower()}'"))
    total = len(found) + small
    if total >= MIN_LINE_STARTS and len(found) > total * MAX_CAPITAL_SHARE:
        ctx.notes["poetry-line-ends"] = (
            f"Not listed: {len(found)} of {total} lines after a comma or semicolon start with a capital, "
            "so this project starts poetry lines with a capital on purpose.")
        return
    yield from found


def check_poetry_long_lines(lines: list[Analysis], ctx: CheckContext) -> Iterator[Finding]:
    """Very long poetry lines without a sentence end inside (those are poetry-two-sentences)."""
    lengths = sorted(len(analysis.segment.text.strip()) for analysis in lines)
    if len(lengths) < MIN_LINES:
        return
    limit = max(lengths[int(len(lengths) * LONG_LINE_SHARE) - 1], round(LONG_LINE_TIMES * lengths[len(lengths) // 2]),
                MIN_LONG)
    two_sentences = long_line_limit(lines)
    marks = _sentence_end_marks(ctx)
    for analysis in lines:
        text = analysis.segment.text
        length = len(text.strip())
        if length <= limit or (length > two_sentences and _sentence_end(text, marks, ctx) is not None):
            continue
        yield analysis.finding(len(text) - len(text.lstrip()), 1, WARNING, "poetry-long-lines", str(length),
                               f"very long poetry line ({length} characters; most poetry lines have about "
                               f"{lengths[len(lengths) // 2]}): maybe break it into two lines")


def check_poetry_verse_inside(lines: list[Analysis], ctx: CheckContext) -> Iterator[Finding]:
    """A verse number inside a poetry line: poetry lines usually start with the verse."""
    for analysis in lines:
        segment = analysis.segment
        for offset, chapter, verse in segment.anchors:
            before = segment.text[:offset]
            if offset <= 0 or not re.search(r"\w\w", before):
                continue
            words = " ".join(before.split()[-3:])
            yield analysis.finding(offset, 1, WARNING, "poetry-verse-inside", f"{chapter}:{verse}",
                                   f"verse {verse} starts inside a poetry line, after '{words}': "
                                   f"maybe start a new line with the verse")


def check_poetry_chapter_break(flow: list[Segment], ctx: CheckContext) -> Iterator[Finding]:
    """Poetry that goes on into the next chapter with no \\b (stanza break) at the end of the chapter and no
    heading: then the chapter is printed with no space before it (a run-on chapter)."""
    for first, second in _pairs(flow):
        if (is_poetry_segment(first) and is_poetry_segment(second) and _chapter(first) != _chapter(second)
                and second.previous_style != "b"):
            yield _finding(second, 0, 1, "poetry-chapter-break", f"{_chapter(first)}-{_chapter(second)}",
                           f"the poetry of chapter {_chapter(first)} goes on in chapter {_chapter(second)} with no "
                           f"\\b (stanza break) at the end of chapter {_chapter(first)} and no heading: is it one "
                           "stanza? If not, add \\b at the end of the chapter")
