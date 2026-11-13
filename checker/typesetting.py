"""Checks from the "finalization" step before typesetting: spaces around markers, notes and quotation marks.

They read the raw files (markers are needed) of the checked books. A Paratext user menu changes these places with
regular expressions; here each place is a warning that says what to change, the text is never changed.

- quote-spaces: two quotation marks of different levels next to each other (”’ or «„) with another space between
  them than the project nearly always uses there (usually a narrow no-break space U+202F).
- digit-hyphens: a hyphen-minus between two digits (10-12) when the project nearly always writes another sign there
  (a non-breaking hyphen ‑ or a dash –). Verse numbers, \\fr, \\xo and link attributes are not counted.
- marker-spaces: a space before the end of a character marker ('the \\nd Lord \\nd*'): the space belongs after it.
- footnote-spaces: a space at the end of a footnote (before \\f*); a space before a footnote when the project nearly
  always writes the note right after the word; a letter right after \\f* (a missing space).
- outline-references: a reference in a book outline line (\\io) without \\ior … \\ior*.
- chapter-end-headings: a heading (\\s, \\ms) as the last line of a chapter: it belongs after the next \\c.
- m-after-heading: \\m (a paragraph that goes on from the text before) right after a heading: the heading
  starts something new, so the paragraph is \\p.
- duplicate-footnotes: a footnote with the same text as a footnote shortly before it (within DUP_DISTANCE
  characters, about a page) without \\cat dup\\cat*. In typesetting, when both are on one page, the second note is
  removed and its caller is the caller of the first one; \\cat dup\\cat* marks the notes for that.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterator

from checker.model import WARNING, CheckContext, Finding
from checker.structure import PERIPHERAL_BOOKS
from checker.usfm import remove_attributes
from checker.verses import RawRefs

MIN_USUAL = 20  # the usual form is used at least this often
MIN_SHARE = 0.9  # and in at least this part of the places
NNBSP = chr(0x202F)
CHARACTER_MARKERS_RE = r"(?:\\\+?[a-z]+\d*\*?[ ]?)*"  # markers between two quotation marks do not count


class _Source:
    """One checked book: the file without attributes, and chapter:verse of an offset."""

    def __init__(self, book: str, content: str) -> None:
        self.book = book
        self.text = remove_attributes(content)
        self._refs: RawRefs | None = None

    def ref(self, offset: int) -> str:
        if self._refs is None:
            self._refs = RawRefs(self.text)
        chapter, verse = self._refs.at(offset)
        return f"{chapter}:{verse}"

    def context(self, start: int, end: int) -> str:
        return " ".join(self.text[max(start - 40, 0):end + 40].split())

    def finding(self, start: int, end: int, check: str, item: str, message: str) -> Finding:
        return Finding(self.book, self.ref(start), WARNING, check, item, message, self.context(start, end))


def _sources(sources: list[tuple[str, str]]) -> list[_Source]:
    return [_Source(book, content) for book, content in sources]


def _usual(counts: Counter) -> str | None:
    """The form used in >=90% of >=20 places, or None."""
    if not counts:
        return None
    usual, count = counts.most_common(1)[0]
    return usual if count >= MIN_USUAL and count >= sum(counts.values()) * MIN_SHARE else None


def _space_name(space: str) -> str:
    if not space:
        return "nothing"
    if space == " ":
        return "a space"
    return " + ".join(f"{unicodedata.name(ch, 'SPACE').lower()} (U+{ord(ch):04X})" for ch in space)


# --- quote-spaces ---

def check_quote_spaces(sources: list[tuple[str, str]], ctx: CheckContext) -> Iterator[Finding]:
    openers = {opener for opener, _ in ctx.settings.quote_levels if opener}
    closers = {closer for _, closer in ctx.settings.quote_levels if closer}
    marks = "".join(sorted(ch for mark in openers | closers for ch in mark))
    if not marks:
        return
    pair_re = re.compile(rf"([{re.escape(marks)}]){CHARACTER_MARKERS_RE}(\s*){CHARACTER_MARKERS_RE}"
                         rf"([{re.escape(marks)}])")
    places = []
    for source in _sources(sources):
        for match in pair_re.finditer(source.text):
            first, second = match.group(1), match.group(3)
            if first == second or "\n" in match.group(2):
                continue
            # Two marks of different levels, both opening (“‘) or both closing (’”).
            if (first in openers and second in openers) or (first in closers and second in closers):
                places.append((source, match))
    usual = _usual(Counter(match.group(2) for _, match in places))
    if usual is None:
        return
    for source, match in places:
        space = match.group(2)
        if space == usual:
            continue
        marks_text = f"{match.group(1)}{space}{match.group(3)}"
        better = f"{match.group(1)}{usual}{match.group(3)}"
        yield source.finding(match.start(), match.end(), "quote-spaces", marks_text,
                             f"change '{marks_text}' to '{better}': between two quotation marks the project nearly "
                             f"always has {_space_name(usual)}, here it has {_space_name(space)}")


# --- digit-hyphens ---

DIGIT_DASH_RE = re.compile(r"(?<=\d)([-\u2010\u2011\u2012\u2013\u2014])(?=\d)")
# Numbers of markers, not text: verse and chapter numbers, \vp, the reference of a note.
NOT_TEXT_BEFORE_RE = re.compile(r"\\(?:v|c|vp|fr|xo)\s[^\\\s]*$")


def check_digit_hyphens(sources: list[tuple[str, str]], ctx: CheckContext) -> Iterator[Finding]:
    places = []
    for source in _sources(sources):
        if source.book in PERIPHERAL_BOOKS:
            continue
        for match in DIGIT_DASH_RE.finditer(source.text):
            if not NOT_TEXT_BEFORE_RE.search(source.text, max(match.start() - 20, 0), match.start()):
                places.append((source, match))
    counts = Counter(match.group(1) for _, match in places)
    others = Counter({sign: count for sign, count in counts.items() if sign != "-"})
    # The project's sign: the most used one; a project that writes "-" itself is left alone.
    if not others or counts["-"] > sum(counts.values()) * (1 - MIN_SHARE) or sum(others.values()) < MIN_USUAL:
        return
    usual = others.most_common(1)[0][0]
    name = unicodedata.name(usual).lower()
    for source, match in places:
        if match.group(1) != "-":
            continue
        number = re.search(r"\d+-\d+", source.text[max(match.start() - 10, 0):match.end() + 10]).group()
        better = number.replace("-", usual)
        yield source.finding(match.start(), match.end(), "digit-hyphens", number,
                             f"change '{number}' to '{better}' ({name} U+{ord(usual):04X}): "
                             f"{sum(others.values())} of {len(places)} such numbers use it")


# --- marker-spaces ---

# A space before the end of a character marker; not \f* \x* \fe* (notes) and not \fv* (special-spaces wants U+202F).
SPACE_BEFORE_END_RE = re.compile(r"(?<=\S)([ \t]+)(\\\+?(?!(?:f|x|fe|ef|ex|fv)\*)[a-z]+\d*\*)")


def check_marker_spaces(sources: list[tuple[str, str]], ctx: CheckContext) -> Iterator[Finding]:
    for source in _sources(sources):
        for match in SPACE_BEFORE_END_RE.finditer(source.text):
            marker = match.group(2)
            word = re.search(r"\S+$", source.text[:match.start()]).group()
            yield source.finding(match.start(), match.end(), "marker-spaces", marker,
                                 f"a space before '{marker}': change '{word} {marker}' to '{word}{marker} ' "
                                 "(the space goes after the end of the marker)")


# --- footnote-spaces ---

SPACE_AT_NOTE_END_RE = re.compile(r"(\s+(?:\\ft\s*)?)\\(fe?)\*")
NOTE_START_RE = re.compile(r"(?<=\S)( *)\\(fe?)\s")
NOTE_END_RE = re.compile(r"\\(fe?)\*(\w)")


def check_footnote_spaces(sources: list[tuple[str, str]], ctx: CheckContext) -> Iterator[Finding]:
    texts = _sources(sources)
    for source in texts:
        for match in SPACE_AT_NOTE_END_RE.finditer(source.text):
            yield source.finding(match.start(), match.end(), "footnote-spaces", f"\\{match.group(2)}*",
                                 f"a space at the end of the note: remove it before '\\{match.group(2)}*'")
    # A note after a word: with or without a space, as the project nearly always writes it.
    starts = [(source, match) for source in texts for match in NOTE_START_RE.finditer(source.text)
              if not re.search(r"\\(?:[a-z]+\d*\*?|v \S+|c \S+)$", source.text[max(match.start() - 12, 0):match.start()])]
    if _usual(Counter(bool(match.group(1)) for _, match in starts)) is False:
        for source, match in starts:
            if match.group(1):
                word = re.search(r"\S+$", source.text[:match.start()]).group()
                yield source.finding(match.start(), match.end(), "footnote-spaces", f"\\{match.group(2)}",
                                     f"a space before the note: change '{word} \\{match.group(2)}' to "
                                     f"'{word}\\{match.group(2)}' (the other notes stand right after the word)")
    # A letter right after the end of a note: a space is missing (unless the project glues them: no spaces).
    ends = Counter()
    for source in texts:
        for match in re.finditer(r"\\fe?\*(.)", source.text):
            ends[match.group(1).isalnum()] += 1
    if ends[True] and ends[True] <= sum(ends.values()) * (1 - MIN_SHARE):
        for source in texts:
            for match in NOTE_END_RE.finditer(source.text):
                word = re.match(r"\w+", source.text[match.start(2):]).group()
                yield source.finding(match.start(), match.end(), "footnote-spaces", f"\\{match.group(1)}*",
                                     f"no space after the note: change '\\{match.group(1)}*{word}' to "
                                     f"'\\{match.group(1)}* {word}'")


# --- outline-references ---

OUTLINE_LINE_RE = re.compile(r"\\io\d*\s([^\n]*)")


def check_outline_references(sources: list[tuple[str, str]], ctx: CheckContext) -> Iterator[Finding]:
    separator = re.escape(ctx.settings.chapter_verse_separator or ":")
    reference_re = re.compile(rf"(?<![\d\w])\d+{separator}\d+(?:[\u2010-\u2014-]\d+(?:{separator}\d+)?)?")
    for source in _sources(sources):
        for line in OUTLINE_LINE_RE.finditer(source.text):
            body = line.group(1)
            outside = re.sub(r"\\ior\s.*?\\ior\*", lambda m: " " * len(m.group()), body)
            for match in reference_re.finditer(outside):
                start = line.start(1) + match.start()
                reference = match.group()
                yield source.finding(start, start + len(reference), "outline-references", reference,
                                     f"mark the reference of the outline line: change '{reference}' to "
                                     f"'\\ior {reference}\\ior*'")


# --- chapter-end-headings ---

PARAGRAPH_RE = re.compile(r"\\([a-z]+\d*)(?=\s)")
HEADING_RE = re.compile(r"(?:s\d*|ms\d*)$")
UNDER_HEADING = frozenset({"r", "mr", "sr", "sp"})  # lines that belong to the heading above them
PARAGRAPH_MARKERS = re.compile(r"(?:c|p|m|pi\d*|mi|nb|pm[ocr]?|po|pr|pc|cls|q\d*|qm\d*|qc|qr|qa|qd|b|s\d*|ms\d*|mr|"
                               r"r|sr|sp|d|li\d*|lim\d*|lf|lh|tr|cl|cd|v)$")


def check_chapter_end_headings(sources: list[tuple[str, str]], ctx: CheckContext) -> Iterator[Finding]:
    for source in _sources(sources):
        if source.book in PERIPHERAL_BOOKS:
            continue
        markers = [(m.group(1), m.start()) for m in PARAGRAPH_RE.finditer(source.text)
                   if PARAGRAPH_MARKERS.match(m.group(1))]
        for index, (name, start) in enumerate(markers):
            if not HEADING_RE.match(name):
                continue
            rest = index + 1
            while rest < len(markers) and markers[rest][0] in UNDER_HEADING:
                rest += 1
            if rest < len(markers) and markers[rest][0] != "c":
                continue
            title = source.text[start:].split("\n", 1)[0][len(name) + 2:].strip()
            where = "the end of the book" if rest == len(markers) else "the end of the chapter"
            yield source.finding(start, start + len(name) + 1, "chapter-end-headings", title,
                                 f"the heading \\{name} '{title}' stands at {where}: move it after the next \\c")


# --- m-after-heading ---

HEADINGS_BEFORE_M = re.compile(r"(?:s\d*|ms\d*|mr|r|d)$")


def check_m_after_heading(sources: list[tuple[str, str]], ctx: CheckContext) -> Iterator[Finding]:
    for source in _sources(sources):
        markers = [(m.group(1), m.start()) for m in PARAGRAPH_RE.finditer(source.text)
                   if PARAGRAPH_MARKERS.match(m.group(1))]
        for (before, _), (name, start) in zip(markers, markers[1:]):
            if name == "m" and HEADINGS_BEFORE_M.match(before):
                yield source.finding(start, start + 2, "m-after-heading", "\\m",
                                     f"change '\\m' to '\\p': a paragraph right after a heading (\\{before}) is a new "
                                     "paragraph, not one that goes on")


# --- duplicate-footnotes ---

DUP_DISTANCE = 7000  # characters of the file from one note to the next: about one printed page
FOOTNOTE_RE = re.compile(r"\\f\s+\S+\s*((?:\\cat\s[^\\]*\\cat\*\s*)?)(?:\\fr\s[^\\]*)?(.*?)\\f\*", re.S)


def check_duplicate_footnotes(sources: list[tuple[str, str]], ctx: CheckContext) -> Iterator[Finding]:
    for source in _sources(sources):
        last: dict[str, tuple[int, int]] = {}  # note text -> (start, end) of the last note with it
        for match in FOOTNOTE_RE.finditer(source.text):
            body = " ".join(match.group(2).split())
            if not body:
                continue
            earlier = last.get(body)
            last[body] = (match.start(), match.end())
            if earlier is None or match.start() - earlier[1] > DUP_DISTANCE:
                continue
            if re.search(r"\bdup\b", match.group(1)):
                continue
            shown = re.sub(r"\\\+?[a-z]+\d*\*?\s?", "", body)
            yield source.finding(match.start(), match.end(), "duplicate-footnotes", shown[:60],
                                 f"the same note is at {source.book} {source.ref(earlier[0])}, shortly before: add '\\cat dup\\cat*' "
                                 "after the caller (\\f + \\cat dup\\cat*\\fr …). When both notes are on one page, "
                                 "typesetting removes this one and gives it the caller of the first")
