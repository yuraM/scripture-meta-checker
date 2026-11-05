"""special-spaces: where the narrow no-break space (U+202F) and the no-break space (~) belong.

Works on the raw file (like `usfm`), because \\fv and the markers between two quotation marks are needed.

1. \\fv: "\\fv 13<U+202F>\\fv*Text": a narrow no-break space before \\fv*, nothing after it (user decision 2026-11-03,
   from the updated typesetting documentation).
2. U+202F anywhere else is only right between two quotation marks (markers and notes between them do not count:
   ’\\wj*<U+202F>”) and where the project settings use it: the thousands separator between digits, a reference mark
   ("," + U+202F in SequenceIndicator) before a number. If the place is an abbreviation that Abbreviations writes
   with ~ (н.~э.), the message gives that form.
3. An abbreviation that Abbreviations writes with ~ (н.~э.) is written with a normal space.
4. A list of numbers after an abbreviation ("ст.~8, 9") is separated by a mark that is not in SequenceIndicator.
"""
from __future__ import annotations

import bisect
import re
import unicodedata
from collections.abc import Iterator

from checker import places
from checker.model import CONTEXT_WIDTH, ERROR, CheckContext, Finding
from checker.usfm import remove_attributes

CHECK = "special-spaces"
NARROW = "\u202f"
NBSP = "\u00a0"
_FV_RE = re.compile(r"\\(\+?)fv[ \t]+([^\\]*?)\\\+?fv\*([ \t\u202f\u00a0~]*)")
_SKIPPED_LINE_RE = re.compile(r"^\\(?:id|rem)\b.*$", re.M)
_CHAPTER_RE = re.compile(r"\\c\s+(\d+)")
_VERSE_RE = re.compile(r"\\v\s+(\S+)")
_CLOSING_MARKER_RE = re.compile(r"\\\+?([a-z0-9]+)\*$")
_OPENING_MARKER_RE = re.compile(r"\\\+?[a-z0-9]+\*?[ ]?")
_XT_RE = re.compile(r"\\\+?xt\s.*?\\\+?xt\*", re.S)
NOTE_ENDS = {"f": r"\f ", "fe": r"\fe ", "x": r"\x ", "ef": r"\ef ", "ex": r"\ex "}
# Ordinary spaces (not the no-break ones): an abbreviation with ~ written with one of these is wrong.
_ORDINARY_SPACE = r"[ \u2000-\u200a\u205f\u3000]"


class _Places:
    """Chapter:verse of a position in the raw file."""

    def __init__(self, content: str) -> None:
        self.chapters = [(m.start(), m.group(1)) for m in _CHAPTER_RE.finditer(content)]
        self.verses = [(m.start(), m.group(1)) for m in _VERSE_RE.finditer(content)]
        self.chapter_starts = [pos for pos, _ in self.chapters]
        self.verse_starts = [pos for pos, _ in self.verses]

    def ref(self, position: int) -> str:
        index = bisect.bisect_right(self.chapter_starts, position) - 1
        if index < 0:
            return "0:0"
        chapter_start, chapter = self.chapters[index]
        verse_index = bisect.bisect_right(self.verse_starts, position) - 1
        verse = self.verses[verse_index][1] if verse_index >= 0 and self.verses[verse_index][0] > chapter_start else "0"
        return f"{chapter}:{verse}"


def _context(content: str, start: int, end: int) -> str:
    left = max(start - CONTEXT_WIDTH, 0)
    # Only line breaks and ordinary spaces are joined: the no-break spaces must stay visible.
    return re.sub(r"[ \t\r\n]+", " ", content[left:end + CONTEXT_WIDTH])


def _quote_marks(ctx: CheckContext) -> frozenset[str]:
    marks = {ch for level in ctx.settings.quote_levels for mark in level for ch in mark}
    marks |= {ch for continuer in ctx.settings.quote_continuers for ch in continuer}
    return frozenset(ch for ch in marks if not ch.isspace())


def _is_quote(ch: str, marks: frozenset[str]) -> bool:
    return bool(ch) and (ch in marks or unicodedata.category(ch) in ("Pi", "Pf") or ch == '"')


def _char_before(content: str, position: int) -> str:
    """The character before a position, passing over closing markers and whole notes (\\f … \\f*)."""
    i = position
    for _ in range(20):
        closing = _CLOSING_MARKER_RE.search(content, max(0, i - 12), i)
        if not closing or closing.end() != i:
            break
        name = closing.group(1)
        if name in NOTE_ENDS:
            start = content.rfind(NOTE_ENDS[name], 0, closing.start())
            i = start if start >= 0 else closing.start()
        else:
            i = closing.start()
    return content[i - 1] if i > 0 else ""


def _char_after(content: str, position: int) -> str:
    """The character after a position, passing over markers (an opening marker with its space)."""
    i = position
    for _ in range(20):
        marker = _OPENING_MARKER_RE.match(content, i)
        if not marker:
            break
        i = marker.end()
    return content[i] if i < len(content) else ""


def _in(ranges: list[tuple[int, int]], position: int) -> bool:
    index = bisect.bisect_right(ranges, (position, float("inf"))) - 1
    return index >= 0 and ranges[index][0] <= position < ranges[index][1]


def check_special_spaces(book: str, content: str, ctx: CheckContext) -> Iterator[Finding]:
    content = remove_attributes(content, keep_links=True)
    places = _Places(content)
    skipped = sorted((m.start(), m.end()) for m in _SKIPPED_LINE_RE.finditer(content))

    def finding(start: int, end: int, item: str, message: str) -> Finding:
        return Finding(book, places.ref(start), ERROR, CHECK, item, message, _context(content, start, end))

    # 1. \fv … \fv*
    fv_spans = []
    for match in _FV_RE.finditer(content):
        fv_spans.append((match.start(), match.end()))
        if _in(skipped, match.start()):
            continue
        plus, number, after = match.groups()
        if number.endswith(NARROW) and not after:
            continue
        following = content[match.end():match.end() + 12].split("\n")[0]
        expected = f"\\{plus}fv {number.rstrip(' ~' + NARROW + NBSP)}{NARROW}\\{plus}fv*{following}"
        yield finding(match.start(), match.end(), f"\\{plus}fv",
                      f"write '{expected}': a narrow no-break space (U+202F) before \\fv*, no space after \\fv*")
    fv_spans.sort()

    settings = ctx.settings
    fmt = settings.reference_format
    tilde_abbreviations = [a for a in settings.abbreviations if "~" in a]
    # 2. U+202F in other places
    marks = _quote_marks(ctx)
    reference_marks = [mark for choices in (fmt.verse_sequences, fmt.chapter_sequences, fmt.verse_ranges,
                                            fmt.chapter_ranges, fmt.book_sequences)
                       for mark in choices if NARROW in mark]
    for match in re.finditer(NARROW, content):
        position = match.start()
        if _in(fv_spans, position) or _in(skipped, position):
            continue
        before, after = content[position - 1:position], content[position + 1:position + 2]
        if settings.number_thousands_separator == NARROW and before.isdigit() and after.isdigit():
            continue
        if any(content[position - mark.index(NARROW):position - mark.index(NARROW) + len(mark)] == mark
               and content[position - mark.index(NARROW) + len(mark):][:1].isdigit() for mark in reference_marks):
            continue
        if _is_quote(_char_before(content, position), marks) and _is_quote(_char_after(content, position + 1), marks):
            continue
        hint = next((a for a in tilde_abbreviations for k, ch in enumerate(a) if ch == "~"
                     and content[position - k:position - k + len(a)].lower() == a.replace("~", NARROW).lower()), None)
        if hint:
            yield finding(position, position + 1, hint,
                          f"write '{hint}' (~ is the normal no-break space), not a narrow no-break space (U+202F)")
            continue
        # The words on both sides, without markers ("ст.⍽29.\f*" -> "ст.⍽29.").
        left = re.search(r"[^\s\\]{0,12}$", content[max(0, position - 12):position]).group()
        right = re.match(r"[^\s\\]{0,12}", content[position + 1:position + 13]).group()
        snippet = f"{left}{NARROW}{right}"
        yield finding(position, position + 1, snippet,
                      f"narrow no-break space (U+202F) in '{snippet}': it belongs only between two quotation marks, "
                      f"inside \\fv … \\fv*, and where the project settings use it")

    # 3. Abbreviations written with ~ in Abbreviations, but with a normal space in the text.
    for abbreviation in tilde_abbreviations:
        parts = [re.escape(part) for part in abbreviation.split("~")]
        for match in re.finditer(r"(?<!\w)" + _ORDINARY_SPACE.join(parts), content, re.I):
            if not _in(skipped, match.start()):
                yield finding(match.start(), match.end(), abbreviation,
                              f"write '{abbreviation}' (~ is the normal no-break space), not '{match.group()}'")

    # 4. Lists of numbers after an abbreviation: the marks between the numbers must be SequenceIndicator marks.
    yield from _list_marks(content, ctx, skipped, finding)


def _list_marks(content: str, ctx: CheckContext, skipped: list[tuple[int, int]], finding) -> Iterator[Finding]:
    choices = ctx.settings.reference_format.verse_sequences
    words = sorted({a[:-1] for a in ctx.settings.abbreviations
                    if a.endswith(".") and a[:-1] and not re.search(r"[\s~.]", a[:-1]) and any(c.isalpha() for c in a)},
                   key=len, reverse=True)
    if not choices or not words:
        return
    letter_marks = [re.escape(mark).replace(NBSP, f"[{NBSP}~]") for mark in choices if any(c.isalpha() for c in mark)]
    separator = r"(?:,[ \u00a0\u202f\u2009~]?" + "".join(f"|{m}" for m in letter_marks) + ")"
    number = r"\d+(?:[-–‒]\d+)?"
    list_re = re.compile(rf"(?<!\w)(?:{'|'.join(map(re.escape, words))})\.[ \u00a0~]?{number}(?:{separator}{number})+")
    separator_re = re.compile(separator + r"(?=\d)")
    references = sorted((m.start(), m.end()) for m in _XT_RE.finditer(content))
    preferred = next((mark for mark in choices if mark.startswith(",")), choices[0])
    for match in list_re.finditer(content):
        if _in(skipped, match.start()) or _in(references, match.start()):
            continue  # references are checked by `references`
        text = match.group()
        start = text.index(".") + 1
        wrong = [m for m in separator_re.finditer(text, start) if m.group().replace("~", NBSP) not in choices]
        if not wrong:
            continue
        fixed = text
        for m in reversed(wrong):
            fixed = fixed[:m.start()] + preferred + fixed[m.end():]
        allowed = " or ".join(f"'{mark}'" for mark in choices)
        yield finding(match.start(), match.end(), text,
                      f"write '{fixed}': between the numbers use {allowed} "
                      f"({places.REFERENCE_FORMAT})")
