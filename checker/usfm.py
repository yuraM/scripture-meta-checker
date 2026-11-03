"""Extract checkable text segments from USFM book files.

A segment is the text of one paragraph (or one footnote / cross reference) with all
markers removed. Verse and chapter numbers, note callers and note references are not
part of the text; their positions are kept as anchors to report locations.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from pathlib import Path

MARKER_RE = re.compile(r"\\(\+?)([A-Za-z0-9]+)(\*?)")
# USFM 3 attributes before a closing character marker: \xt 8-му|GEN 2:8\xt* -> "8-му".
_ATTRIBUTES_RE = re.compile(r"\|[^\\|]*(?=\\\+?[A-Za-z0-9]+\*)")
# USFM 3 named attributes after any marker: \periph Title Page|id="title", \w Bible|lemma="b" strong="H1".
# A value may hold a backslash (\fig |src="C:\Users\a.jpg"), so values are matched in their quotes.
_NAMED_ATTRIBUTES_RE = re.compile(r"""\|[ \t]*(?:[A-Za-z][\w-]*[ \t]*=[ \t]*"[^"\r\n]*"[ \t]*)+""")
_LINK_ATTRIBUTE_RE = re.compile(
    r"""\|[ \t]*(?:[A-Za-z][\w-]*[ \t]*=[ \t]*"[^"\r\n]*"[ \t]*)*?link-href[ \t]*=[ \t]*"([^"\r\n]*)"[^|\\\r\n]*""")
# USFM 3 milestones (no text): \qt-s |sid="q1"\*, \ts\*, \zgetperiph |id="intbible"\* (after the attributes are gone).
_MILESTONE_RE = re.compile(r"\\[A-Za-z0-9]+(?:-[se])?[ \t]*\\\*")
_MILESTONE_START_END_RE = re.compile(r"\\[A-Za-z0-9]+-[se]\b[ \t]*")


def remove_attributes(content: str, keep_links: bool = False) -> str:
    """Remove USFM 3 attributes and milestones, which are not text.

    keep_links: \\xt 9|link-href="GEN 2:9"\\xt* becomes \\xt 9|GEN 2:9\\xt* (the form the reference check reads),
    and default attributes (\\xt 8|GEN 2:8\\xt*) stay; otherwise they are removed too.
    """
    if keep_links:
        content = _LINK_ATTRIBUTE_RE.sub(lambda m: "|" + m.group(1), content)
    content = _NAMED_ATTRIBUTES_RE.sub("", content)
    content = _MILESTONE_RE.sub("", content)
    content = _MILESTONE_START_END_RE.sub("", content)
    return content if keep_links else _ATTRIBUTES_RE.sub("", content)


# \periph Title Page: the rest of the line names the division for the software; it is not printed text.
_PERIPH_TITLE_RE = re.compile(r"(\\periph)\b[^\r\n]*")
# "//" with its spaces: a space on either side must leave one space, not two.
_OPTIONAL_BREAK_RE = re.compile(r"( *)//( *)")
# A line break (with surrounding spaces/tabs) inside a paragraph is a single space.
_NEWLINE_RE = re.compile(r"[ \t]*(?:\r?\n[ \t]*)+")

NOTE_MARKERS = frozenset({"f", "fe", "ef", "x", "ex"})
CHARACTER_MARKERS = frozenset({
    # Main text character styles.
    "add", "bk", "dc", "k", "nd", "ord", "pn", "png", "addpn", "qt", "sig", "sls", "tl", "wj",
    "em", "bd", "it", "bdit", "no", "sc", "sup", "w", "wg", "wh", "wa", "rb", "pro", "lit",
    "qac", "qs", "rq", "jmp", "ior", "iqt", "xt", "litl", "lik", "liv", "liv1", "liv2", "liv3",
    # Footnote and cross reference content.
    "ft", "fq", "fqa", "fk", "fl", "fw", "fp", "fdc", "fm", "xk", "xq", "xta", "xop", "xot", "xnt", "xdc",
})
# Markers whose text (up to the next marker) is not checked: references and comments.
SKIPPED_TEXT_MARKERS = frozenset({"fr", "xo", "fv", "rem", "cp", "restore", "sts"})
# Markers whose content is skipped up to the matching closing marker.
SKIPPED_SPAN_MARKERS = frozenset({"fig", "ca", "va", "vp", "cat"})


@dataclass(frozen=True)
class Segment:
    book: str
    style: str
    in_note: bool
    text: str
    # (offset, chapter, verse), sorted by offset.
    anchors: tuple[tuple[int, str, str], ...]
    # Style of the paragraph marker before this one, including empty ones such as .
    previous_style: str = ""
    # Character style spans (start, end, marker), e.g. (12, 19, "nd") for "\nd Господь\nd*".
    spans: tuple[tuple[int, int, str], ...] = ()

    def styles_at(self, offset: int) -> frozenset[str]:
        return frozenset(name for start, end, name in self.spans if start <= offset < end)

    def ref_at(self, offset: int) -> str:
        index = bisect.bisect_right([a[0] for a in self.anchors], offset) - 1
        _, chapter, verse = self.anchors[max(index, 0)]
        return f"{chapter}:{verse}"


@dataclass
class _SegmentBuilder:
    style: str
    in_note: bool
    previous_style: str = ""
    parts: list[str] = field(default_factory=list)
    length: int = 0
    anchors: list[tuple[int, str, str]] = field(default_factory=list)
    open_spans: list[tuple[str, int]] = field(default_factory=list)
    spans: list[tuple[int, int, str]] = field(default_factory=list)

    def open_span(self, name: str) -> None:
        self.open_spans.append((name, self.length))

    def close_span(self, name: str) -> None:
        for index in range(len(self.open_spans) - 1, -1, -1):
            if self.open_spans[index][0] == name:
                self.spans.append((self.open_spans[index][1], self.length, name))
                del self.open_spans[index]
                return

    def add(self, text: str, chapter: str, verse: str) -> None:
        leading_break = _NEWLINE_RE.match(text)
        if leading_break and (not self.length or self.parts[-1][-1].isspace()):
            text = text[leading_break.end():]
        text = _NEWLINE_RE.sub(" ", text)
        if not text:
            return
        if not self.anchors or self.anchors[-1][1:] != (chapter, verse):
            self.anchors.append((self.length, chapter, verse))
        self.parts.append(text)
        self.length += len(text)

    def build(self, book: str) -> Segment | None:
        raw = "".join(self.parts)
        text = raw.strip()
        if not text:
            return None
        shift = len(raw) - len(raw.lstrip())
        anchors = tuple((max(offset - shift, 0), chapter, verse) for offset, chapter, verse in self.anchors)
        # Spans still open at the paragraph end end there.
        spans = self.spans + [(start, self.length, name) for name, start in self.open_spans]
        spans = tuple(sorted((max(start - shift, 0), min(end - shift, len(text)), name)
                             for start, end, name in spans if end > start))
        return Segment(book, self.style, self.in_note, text, anchors, self.previous_style, spans)


def _split_first_token(text: str) -> tuple[str, str]:
    """Split "12 rest" into ("12", "rest"); used for chapter/verse numbers and note callers."""
    stripped = text.lstrip()
    token, _, rest = stripped.partition(" ")
    if "\n" in token:
        token, _, tail = token.partition("\n")
        rest = "\n" + tail + (" " + rest if rest else "")
    return token.strip(), rest


class _BookParser:
    def __init__(self, book: str) -> None:
        self.book = book
        self.id_seen = False
        self.chapter = "0"
        self.verse = "0"
        self.segments: list[Segment] = []
        self.main: _SegmentBuilder | None = None
        self.note: _SegmentBuilder | None = None
        self.pending_notes: list[_SegmentBuilder] = []
        self.last_paragraph_style = ""
        self.skip_until: str | None = None

    def parse(self, content: str) -> list[Segment]:
        content = _PERIPH_TITLE_RE.sub(r"\1", remove_attributes(content))
        # "//" is the USFM optional line break, not text.
        content = _OPTIONAL_BREAK_RE.sub(lambda m: " " if m.group(1) or m.group(2) else "", content)
        matches = list(MARKER_RE.finditer(content))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            self._handle(match.group(2), bool(match.group(3)), content[match.end():end])
        self._close_note()
        self._close_main()
        return self.segments

    def _handle(self, name: str, closing: bool, text: str) -> None:
        if self.skip_until:
            if closing and name == self.skip_until:
                self.skip_until = None
                self._add(self._after_removed(text))
            return
        if closing:
            if name in NOTE_MARKERS:
                self._close_note()
            elif self.note or self.main:
                (self.note or self.main).close_span(name)
            self._add(self._after_removed(text) if name in SKIPPED_TEXT_MARKERS else text)
            return
        # The single space or line break after an opening marker belongs to the marker.
        if text[:1] in (" ", "\n"):
            text = text[1:]
        elif text[:2] == "\r\n":
            text = text[2:]

        if name == "id":
            self._close_note()
            self._close_main()
            code = text.strip().split(" ", 1)[0]
            # Paratext reads only the first \id; a second one is reported by the usfm check.
            if code and not self.id_seen:
                self.book = code.upper()
                self.id_seen = True
        elif name == "c":
            self._close_note()
            self._close_main()
            self.chapter, _ = _split_first_token(text)
            self.verse = "0"
        elif name == "v":
            self.verse, rest = _split_first_token(text)
            self._add(rest)
        elif name in NOTE_MARKERS:
            self._close_note()
            _, rest = _split_first_token(text)  # drop the caller ("+", "-" or a letter)
            self.note = _SegmentBuilder(style=name, in_note=True)
            self._add(rest)
        elif name in SKIPPED_SPAN_MARKERS:
            self.skip_until = name
        elif name in SKIPPED_TEXT_MARKERS:
            if not self.note:
                self._close_main()
        elif name in CHARACTER_MARKERS:
            if not (self.note or self.main):
                self.main = _SegmentBuilder(style="", in_note=False)
            (self.note or self.main).open_span(name)
            self._add(text)
        else:  # paragraph marker
            self._close_note()
            self._close_main()
            self.main = _SegmentBuilder(style=name, in_note=False, previous_style=self.last_paragraph_style)
            self.last_paragraph_style = name
            self._add(text)

    def _after_removed(self, text: str) -> str:
        """Removed text ("а \\fv 6\\fv* б") must not join the spaces around it into two spaces."""
        target = self.note or self.main
        if target and target.parts and target.parts[-1][-1] == " " and text[:1] == " ":
            return text[1:]
        return text

    def _add(self, text: str) -> None:
        target = self.note or self.main
        if target is None:
            if not text.strip():
                return
            target = self.main = _SegmentBuilder(style="", in_note=False)
        target.add(text, self.chapter, self.verse)

    def _close_note(self) -> None:
        # Notes are emitted after their paragraph so that findings stay in reading order.
        if self.note:
            self.pending_notes.append(self.note)
            self.note = None
            if not self.main:
                self._flush_notes()

    def _close_main(self) -> None:
        if self.main:
            self._emit(self.main)
            self.main = None
        self._flush_notes()

    def _flush_notes(self) -> None:
        for note in self.pending_notes:
            self._emit(note)
        self.pending_notes.clear()

    def _emit(self, builder: _SegmentBuilder) -> None:
        segment = builder.build(self.book)
        if segment:
            self.segments.append(segment)


def parse_usfm(content: str, book: str = "") -> list[Segment]:
    return _BookParser(book).parse(content)


def parse_book(path: Path) -> list[Segment]:
    return parse_usfm(path.read_text(encoding="utf-8-sig"), book=path.stem[:5])
