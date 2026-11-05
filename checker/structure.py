"""USFM structure of a book file: paired markers, notes, chapter and verse numbering.

Works on the raw file content, because the segments used by the text checks have no markers.
The same scan also indexes the book for the project-level `references` check: which
chapters/verses exist, the book's names (\\toc1-3) and the \\xt references it contains.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from checker.model import ERROR, WARNING, CONTEXT_WIDTH, Finding
from checker.quotes import ISOLATED_STYLES, ISOLATED_STYLE_PREFIXES
from checker.references import parse_reference
from checker.settings import ReferenceFormat
from checker.usfm import CHARACTER_MARKERS, MARKER_RE, NOTE_MARKERS, SKIPPED_SPAN_MARKERS, remove_attributes

CHECK = "usfm"
TITLES_CHECK = "book-titles"
# Character markers that live inside notes; they are closed implicitly by the next one or by the note end.
NOTE_CONTENT_MARKERS = frozenset({
    "fr", "ft", "fq", "fqa", "fk", "fl", "fw", "fp", "fv", "fdc", "fm",
    "xo", "xk", "xq", "xt", "xta", "xop", "xot", "xnt", "xdc",
})
PAIRED_MARKERS = CHARACTER_MARKERS | SKIPPED_SPAN_MARKERS
# Markers that do not end a paragraph (everything else that is not paired starts a new paragraph).
INLINE_MARKERS = frozenset({"v", "rem"}) | {"fr", "xo", "fv", "cp", "restore", "sts"}
# Note markers whose text is the reference of the note ("\fr 2:19 ").
NOTE_REFERENCE_MARKERS = frozenset({"fr", "xo"})
BOOK_NAME_MARKERS = frozenset({"toc1", "toc2", "toc3"})
# USFM peripheral books: no chapter/verse numbering to check.
PERIPHERAL_BOOKS = frozenset({"FRT", "BAK", "OTH", "INT", "CNC", "GLO", "TDX", "NDX",
                              "XXA", "XXB", "XXC", "XXD", "XXE", "XXF", "XXG"})
_NUMBER_RE = re.compile(r"(\d+)[a-z]?(?:[-‐–](\d+)[a-z]?)?$")
_BOOK_NAME_RE = re.compile(r"\\toc[123]\s+(.+)")
_ID_RE = re.compile(r"\\id\s+(\S+)")


@dataclass
class _Open:
    name: str
    offset: int
    ref: str


@dataclass(frozen=True)
class XtReference:
    """Text of one \\xt, e.g. "Бут. 1:1; 2:3" or "8-му|GEN 2:8" (with a link attribute)."""
    book: str
    ref: str
    text: str
    context: str
    marker: str = "xt"


@dataclass
class BookIndex:
    verses: dict[int, set[int]] = field(default_factory=dict)
    names: set[str] = field(default_factory=set)
    references: list[XtReference] = field(default_factory=list)
    note_references: list[XtReference] = field(default_factory=list)  # the text of \fr and \xo


def verse_range(number: str) -> tuple[int, int] | None:
    """"5" -> (5, 5), "6-7" -> (6, 7), "5a" -> (5, 5); None if it is not a verse number."""
    parsed = _NUMBER_RE.match(number)
    if not parsed:
        return None
    first = int(parsed.group(1))
    return first, int(parsed.group(2) or first)


def _is_heading(style: str) -> bool:
    # \d (psalm title) is often part of verse 1, so its text counts.
    return style != "d" and (style in ISOLATED_STYLES or style.startswith(ISOLATED_STYLE_PREFIXES))


class _StructureScanner:
    def __init__(self, book: str, content: str, reference_format: ReferenceFormat = ReferenceFormat()) -> None:
        self.book = book
        self.content = content = remove_attributes(content, keep_links=True)
        self.reference_format = reference_format
        self.chapter = 0
        self.verse = "0"
        self.last_verse = 0
        self.spans: list[_Open] = []       # open character markers of the main text
        self.note: _Open | None = None
        self.note_spans: list[_Open] = []  # open character markers inside the current note
        self.skip: str | None = None       # open \fig, \vp ... whose content is not text
        self.paragraph = ""
        self.verse_start: int | None = None  # offset of the current \v while it has no text yet
        # Any marker closed somewhere in the file is a character marker, also ones missing from our list.
        self.paired = PAIRED_MARKERS | {m.group(2) for m in MARKER_RE.finditer(content) if m.group(3)}
        self.numbered = book not in PERIPHERAL_BOOKS
        self.index = BookIndex()

    @property
    def ref(self) -> str:
        return f"{self.chapter}:{self.verse}"

    def context(self, offset: int) -> str:
        left = max(offset - CONTEXT_WIDTH, 0)
        return " ".join(self.content[left:offset + CONTEXT_WIDTH * 2].split())

    def finding(self, offset: int, severity: str, item: str, message: str, ref: str | None = None) -> Finding:
        return Finding(self.book, ref or self.ref, severity, CHECK, item, message, self.context(offset))

    def scan(self) -> Iterator[Finding]:
        matches = list(MARKER_RE.finditer(self.content))
        for position, match in enumerate(matches):
            plus, name, closing = match.group(1), match.group(2), bool(match.group(3))
            following = matches[position + 1].start() if position + 1 < len(matches) else len(self.content)
            text = self.content[match.end():following]
            if closing:
                yield from self._close(name, match.start())
                if name == self.skip:
                    self.skip = None
            elif name in NOTE_MARKERS:
                yield from self._close_note(match.start(), implicit=True)
                yield from self._open_note(name, match.start())
                continue
            elif name in self.paired:
                yield from self._open(name, bool(plus), match.start())
                if name in SKIPPED_SPAN_MARKERS:
                    self.skip = name
                elif name == "xt" or (self.note and name in NOTE_REFERENCE_MARKERS):
                    yield from self._note_text(name, match.start(), text)
                    continue
            elif name == "c":
                yield from self._end_verse()
                yield from self._end_paragraph(match.start())
                yield from self._chapter(match)
                continue
            elif name == "v":
                yield from self._end_verse()
                yield from self._verse(match)
                text = text.lstrip(" ")[len(self._number(match)):]
            elif name in NOTE_REFERENCE_MARKERS:
                yield from self._note_text(name, match.start(), text)
                continue
            elif name in BOOK_NAME_MARKERS:
                if text.strip():
                    self.index.names.add(text.strip())
                continue
            elif name not in INLINE_MARKERS:
                yield from self._end_paragraph(match.start())
                self.paragraph = name
                if name == "rem":
                    continue
            if text.strip() and not self.note and not self.skip and not _is_heading(self.paragraph):
                self.verse_start = None
        yield from self._end_verse()
        yield from self._end_paragraph(len(self.content))

    def _number(self, match: re.Match) -> str:
        rest = self.content[match.end():match.end() + 40].lstrip(" ")
        return rest.split(maxsplit=1)[0] if rest.strip() else ""

    def _chapter(self, match: re.Match) -> Iterator[Finding]:
        number = self._number(match)
        if not self.numbered:
            return
        if not number.isdigit():
            yield self.finding(match.start(), ERROR, "\\c", f"wrong chapter number '{number}'")
            return
        chapter = int(number)
        if chapter <= self.chapter:
            yield self.finding(match.start(), ERROR, "\\c", f"wrong order: chapter {chapter} comes after chapter {self.chapter}",
                               ref=f"{chapter}:0")
        elif chapter > self.chapter + 1:
            missing = _span(self.chapter + 1, chapter - 1)
            yield self.finding(match.start(), ERROR, "\\c", f"chapter {missing} is missing", ref=f"{chapter}:0")
        self.chapter, self.verse, self.last_verse = chapter, "0", 0
        self.index.verses.setdefault(chapter, set())

    def _verse(self, match: re.Match) -> Iterator[Finding]:
        number = self._number(match)
        if not self.numbered:
            self.verse = number
            return
        parsed = verse_range(number)
        if not parsed:
            yield self.finding(match.start(), ERROR, "\\v", f"wrong verse number '{number}'")
            return
        first, last = parsed
        previous = self.verse
        self.verse = number
        self.verse_start = match.start()
        self.index.verses.setdefault(self.chapter, set()).update(range(first, last + 1))
        if not self.chapter:
            yield self.finding(match.start(), ERROR, "\\v", f"verse {number} comes before the first chapter")
        if last < first:
            yield self.finding(match.start(), ERROR, "\\v", f"wrong verse range '{number}'")
        # Verse parts ("5a", "5b") repeat the number of the previous verse.
        is_part = first == self.last_verse and number != previous and not number.isdigit() \
            and not previous.isdigit()
        if first <= self.last_verse and not is_part:
            yield self.finding(match.start(), ERROR, "\\v", f"wrong order: verse {number} comes after verse {previous}")
        elif first > self.last_verse + 1:
            missing = _span(self.last_verse + 1, first - 1)
            yield self.finding(match.start(), WARNING, "\\v", f"verse {missing} is missing")
        self.last_verse = max(self.last_verse, last)

    def _end_verse(self) -> Iterator[Finding]:
        if self.verse_start is not None:
            yield self.finding(self.verse_start, WARNING, "empty verse", f"verse {self.verse} has no text")
        self.verse_start = None

    def _note_text(self, name: str, offset: int, text: str) -> Iterator[Finding]:
        """\\fr / \\xo must name the verse the note is in; \\xt references are collected."""
        if name == "xt":
            if text.strip():
                self.index.references.append(XtReference(self.book, self.ref, text.strip(), self.context(offset)))
            return
        if not self.numbered or not self.chapter:
            return
        shown = text.strip()
        if shown:
            self.index.note_references.append(XtReference(self.book, self.ref, shown, self.context(offset), marker=name))
        # "2:19", "14:5–6", "11:12,13": the referenced verses must include the current one.
        parts = parse_reference(text, self.reference_format)[0]
        current = verse_range(self.verse)
        if not parts or not current:
            return
        named = [current]
        if _is_heading(self.paragraph):  # a heading stands before the next verse, so a note in it may name that verse
            named.append((current[1] + 1, current[1] + 1))
        if not any(part.includes(self.chapter, *verses) for part in parts for verses in named):
            yield self.finding(offset, ERROR, f"\\{name}", f"footnote reference \\{name} {shown} does not name "
                                                           f"this verse (chapter {self.chapter}, verse {self.verse})")

    def _open(self, name: str, nested: bool, offset: int) -> Iterator[Finding]:
        spans = self.note_spans if self.note else self.spans
        if self.note and not nested:
            # Inside a note a new character marker closes the previous ones (\fr ... \ft ... \fq ...).
            spans.clear()
        elif nested and not spans:
            yield self.finding(offset, WARNING, f"\\+{name}", f"marker \\+{name} must be inside another marker")
        spans.append(_Open(name, offset, self.ref))

    def _close(self, name: str, offset: int) -> Iterator[Finding]:
        if name in NOTE_MARKERS:
            if self.note and self.note.name == name:
                yield from self._close_note(offset, implicit=False)
            else:
                yield self.finding(offset, ERROR, f"\\{name}*", f"\\{name}* closes a note, but no note is open")
            return
        spans = self.note_spans if self.note else self.spans
        index = next((i for i in range(len(spans) - 1, -1, -1) if spans[i].name == name), None)
        if index is None:
            if not (self.note and name in NOTE_CONTENT_MARKERS):  # "\fv 3\fv*" after an implicit close
                yield self.finding(offset, ERROR, f"\\{name}*", f"\\{name}* has no opening \\{name}")
            return
        for inner in spans[index + 1:]:
            yield self.finding(inner.offset, ERROR, f"\\{inner.name}",
                               f"\\{inner.name} must be closed before \\{name}*", ref=inner.ref)
        del spans[index:]

    def _open_note(self, name: str, offset: int) -> Iterator[Finding]:
        self.note = _Open(name, offset, self.ref)
        self.note_spans = []
        return iter(())

    def _close_note(self, offset: int, implicit: bool) -> Iterator[Finding]:
        if self.note and implicit:
            yield self.finding(self.note.offset, ERROR, f"\\{self.note.name}",
                               f"note \\{self.note.name} has no closing \\{self.note.name}*", ref=self.note.ref)
        if self.note:
            for inner in self.note_spans:
                if inner.name not in NOTE_CONTENT_MARKERS:
                    yield self.finding(inner.offset, ERROR, f"\\{inner.name}",
                                       f"\\{inner.name} is not closed at the end of the note", ref=inner.ref)
        self.note = None
        self.note_spans = []

    def _end_paragraph(self, offset: int) -> Iterator[Finding]:
        yield from self._close_note(offset, implicit=True)
        for span in self.spans:
            yield self.finding(span.offset, ERROR, f"\\{span.name}",
                               f"\\{span.name} is not closed at the end of the paragraph", ref=span.ref)
        self.spans = []


def _span(first: int, last: int) -> str:
    return str(first) if first == last else f"{first}-{last}"


def check_structure(book: str, content: str, reference_format: ReferenceFormat = ReferenceFormat()) -> Iterator[Finding]:
    yield from _StructureScanner(book, content, reference_format).scan()


def check_file(book: str, content: str, file_name: str, name_book: str | None) -> Iterator[Finding]:
    """The book of a file: one \\id, and the same book as the file name says (`name_book`; None = not known)."""
    def finding(offset: int, item: str, message: str) -> Finding:
        left = max(offset - CONTEXT_WIDTH, 0)
        context = " ".join(content[left:offset + CONTEXT_WIDTH * 2].split())
        return Finding(book, "0:0", ERROR, CHECK, item, message, context)

    ids = list(_ID_RE.finditer(content))
    for match in ids[1:]:
        code = match.group(1).upper()
        yield finding(match.start(), f"\\id {code}",
                      f"the file {file_name} has a second \\id ({code}): one file must have one book. "
                      f"Paratext uses only the first \\id ({book})")
    if name_book and ids and name_book != book:
        yield finding(ids[0].start(), f"{name_book} \\id {book}",
                      f"the file name {file_name} is for the book {name_book}, but \\id says {book}")


_NOTE_RE = re.compile(r"\\(f|fe|ef|x|ex)\b.*?\\\1\*", re.DOTALL)
_TITLE_MARKERS = re.compile(r"mt\d?$")


def _book_head_lines(content: str) -> list[tuple[str, str]]:
    """(paragraph marker, its text without notes and character markers) for the lines before the first \\c."""
    first_chapter = re.search(r"\\c\s", content)
    head = remove_attributes(content[:first_chapter.start()] if first_chapter else content)
    head = _NOTE_RE.sub(" ", head).replace("//", " ")
    lines: list[tuple[str, str]] = []
    for match in MARKER_RE.finditer(head):
        plus, name, closing = match.groups()
        if plus or closing or name in PAIRED_MARKERS or name in NOTE_CONTENT_MARKERS:
            continue
        lines.append((name, ""))
        following = MARKER_RE.finditer(head, match.end())
        end = next((m.start() for m in following if not (m.group(1) or m.group(3) or m.group(2) in PAIRED_MARKERS
                                                         or m.group(2) in NOTE_CONTENT_MARKERS)), len(head))
        lines[-1] = (name, " ".join(MARKER_RE.sub(" ", head[match.end():end]).split()))
    return lines


def check_book_titles(book: str, content: str) -> Iterator[Finding]:
    """\\toc1 = the main title (\\mt2 + \\mt1, all \\mt# lines in file order); \\toc2 = \\h."""
    lines = _book_head_lines(content)
    first = {}
    for name, text in lines:
        first.setdefault(name, text)
    titles = [(name, text) for name, text in lines if _TITLE_MARKERS.match(name)]

    def finding(item: str, message: str) -> Finding:
        return Finding(book, "0:0", WARNING, TITLES_CHECK, item, message, "")

    title = " ".join(text for _, text in titles if text)
    if "toc1" in first and titles and first["toc1"] != title:
        parts = " + ".join(f"\\{name}" for name, _ in titles)
        if not title:
            yield finding("empty title", f"the main title ({parts}) is empty; the long book name \\toc1 is "
                                         f"'{first['toc1']}'")
        else:
            yield finding(f"toc1 {first['toc1']} / {title}",
                          f"the long book name \\toc1 '{first['toc1']}' is not the same as the main title "
                          f"'{title}' ({parts})")
    header = first.get("h", first.get("h1"))
    if "toc2" in first and header is not None and first["toc2"] != header:
        yield finding(f"toc2 {first['toc2']} / {header}",
                      f"the short book name \\toc2 '{first['toc2']}' is not the same as the running header \\h "
                      f"'{header}'")


def index_book(book: str, content: str, reference_format: ReferenceFormat = ReferenceFormat()) -> BookIndex:
    scanner = _StructureScanner(book, content, reference_format)
    for _ in scanner.scan():
        pass
    return scanner.index


def book_name_words(content: str, names_only: bool = False) -> set[str]:
    """Lowercase words of the book's \\toc1-3 names: {"1ዜና", "1", "сам", ...}.

    names_only: only words written with a capital letter ("Surat Paulus kepada Jemaat di Roma" -> surat, paulus,
    jemaat, roma; not "kepada", "di"); in scripts without capitals every word.
    """
    words = (word.rstrip(".").replace("~", " ") for name in _BOOK_NAME_RE.findall(content) for word in name.split())
    return {word.lower() for word in words if word and (not names_only or not word[0].islower())}
