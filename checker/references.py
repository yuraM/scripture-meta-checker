"""Read Scripture references ("Бут. 1:1–3, 5; 2:3", "ዘፍ 1፥1‑3፣5፤ 2፥3") using the marks from Settings.xml.

Wrong marks are reported as issues, but the reference is still read: a dash (Unicode category Pd)
is taken as a range, anything else as a list. With an empty ReferenceFormat list no issue is
reported for that kind of mark, so link attributes ("GEN 14:19,20,22") use the same reader.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from checker.settings import ReferenceFormat
from checker.tokens import LETTER

# Both numbers around one sign: "1:2", "1፥2", "3–5".
_TWO_NUMBERS_RE = re.compile(r"(\d+)(\s*)([^\w\s])(\s*)(\d+)")
# A verse part directly after the number: "5a", "42ለ".
_VERSE_PART_RE = re.compile(rf"{LETTER}(?!{LETTER})")
# A number that is not the start of a book name such as "1ዜና": its mark before it, the number, a verse part.
_BARE_NUMBER_RE = re.compile(rf"(\D*?)(\d+)(?!\d)(?:{LETTER}(?!{LETTER}))?(?!{LETTER})")
# A book name at the end of a text: "Мт.", "1 Сам.", "1ዜና", "2 Raja-raja".
_NAME_WORD = rf"{LETTER}+(?:[-‐‑'’]{LETTER}+)*\.?"
_TAIL_NAME_RE = re.compile(rf"(?:\d+\s?)?{_NAME_WORD}(?:\s+{_NAME_WORD})*\s*$")
# Whole chapters at the end of a text, after a space: " 37; 39; " (numbers and marks that are not letters).
_TAIL_CHAPTERS_RE = re.compile(r"(?<=\s)\d+(?:[^\w\d]+\d+)*[^\w\d]*$")


@dataclass(frozen=True)
class ReferenceIssue:
    item: str
    message: str
    # True: the text may be correct, a person must decide (a warning, not an error).
    is_question: bool = False


@dataclass
class ReferencePart:
    """One "chapter:verse..." of a reference. An empty name = the same book as the part before."""
    name: str
    chapter: int
    # Verse spans in the chapter: "5–7, 9" -> [(5, 7), (9, 9)].
    verses: list[tuple[int, int]] = field(default_factory=list)
    # The end of a range over several chapters: "1:7—6:15" -> (6, 15).
    end: tuple[int, int] | None = None

    def includes(self, chapter: int, first: int, last: int) -> bool:
        """Do the verses first..last of this chapter overlap this part?"""
        if self.end:
            start = (self.chapter, self.verses[0][0])
            return start <= (chapter, last) and (chapter, first) <= self.end
        return chapter == self.chapter and any(low <= last and first <= high for low, high in self.verses)


def _is_chapter_verse_mark(mark: str, fmt: ReferenceFormat) -> bool:
    """The project's own mark, or a sign that can only be a wrong one: any colon or full stop by Unicode name."""
    if mark == fmt.chapter_verse:
        return True
    name = unicodedata.name(mark, "")
    return (name.endswith("COLON") and not name.endswith("SEMICOLON")) or name.endswith("FULL STOP")


def _chapter_verses(text: str, fmt: ReferenceFormat) -> Iterator[re.Match]:
    position = 0
    while match := _TWO_NUMBERS_RE.search(text, position):
        if _is_chapter_verse_mark(match.group(3), fmt):
            yield match
            position = match.end()
        else:
            position = match.start(3)


def _is_dash(mark: str) -> bool:
    mark = mark.strip()
    return len(mark) == 1 and unicodedata.category(mark) == "Pd"


def _choices(marks: Sequence[str]) -> str:
    return " or ".join(f"'{mark}'" for mark in marks)


def _wrong_mark(mark: str, where: str, allowed: Sequence[str]) -> ReferenceIssue:
    return ReferenceIssue(mark, f"wrong mark '{mark}' {where}: use {_choices(allowed)}")


def split_tail_name(text: str) -> tuple[str, str]:
    """Text before the book name at its end, and the name: "; 1 Сам. " -> ("; ", "1 Сам.")."""
    match = _TAIL_NAME_RE.search(text)
    return (text[:match.start()], match.group().strip()) if match else (text, "")


def _split_name(text: str) -> tuple[str, str, str]:
    """Like split_tail_name, but whole chapters after the name are passed over: "См. Нав. 2; " ->
    ("См. ", "Нав.", "2; "). In "Нав. 2; 6:22" the verse 6:22 is in that book too."""
    before, name = split_tail_name(text)
    if name:
        return before, name, ""
    chapters = _TAIL_CHAPTERS_RE.search(text)
    if chapters and chapters.start() > 0 and (named := _TAIL_NAME_RE.search(text[:chapters.start()] + " ")):
        return text[:named.start()], named.group().strip(), chapters.group()
    return text, "", ""


def _chapters_question(name: str, chapters: str, fmt: ReferenceFormat) -> ReferenceIssue:
    """Whole chapters after a book name ("Быт. 37; 39;", "Mwa 19; 22;"): a list of chapters, or a ':' missing?"""
    numbers = ", ".join(re.findall(r"\d+", chapters))
    return ReferenceIssue(f"{name} {chapters.strip()}",
                          f"{name} {numbers}: whole chapters, or is '{fmt.chapter_verse}' missing (chapter"
                          f"{fmt.chapter_verse}verse)?", is_question=True)


def _split_gap(gap: str, fmt: ReferenceFormat) -> tuple[str, str, str]:
    """Like _split_name, but a mark made of letters (a word from Settings.xml) is not a book name."""
    if any(gap.endswith(mark) and any(ch.isalpha() for ch in mark) for mark in (*fmt.chapter_sequences, *fmt.book_sequences)):
        return gap, "", ""
    return _split_name(gap)


def _read_verses(part: ReferencePart, text: str, fmt: ReferenceFormat, issues: list[ReferenceIssue]) -> str:
    """Add the numbers after the first verse ("–7, 9"); returns the text left after the last number."""
    position = 0
    while match := _BARE_NUMBER_RE.match(text, position):
        mark, number = match.group(1), int(match.group(2))
        # A word that is not one of the marks: the rest is not a verse list ("; Ос. 1—3", "1:2 та 5").
        if mark not in (*fmt.verse_ranges, *fmt.verse_sequences) and any(ch.isalpha() for ch in mark):
            break
        position = match.end()
        if mark in fmt.verse_ranges:
            is_range = True
        elif mark in fmt.verse_sequences:
            is_range = False
        elif mark in fmt.chapter_sequences or mark in fmt.book_sequences:
            issues.append(ReferenceIssue(
                str(number), f"number {number} has no chapter: if it is a verse, use {_choices(fmt.verse_sequences)}; "
                             "if it is a chapter, this is correct", is_question=True))
            continue
        else:
            is_range = _is_dash(mark)
            if fmt.verse_ranges or fmt.verse_sequences:
                allowed = fmt.verse_ranges if is_range else fmt.verse_sequences
                issues.append(_wrong_mark(mark, "in a verse range" if is_range else "between verses", allowed))
        first, last = part.verses[-1]
        if is_range:
            if number < last:
                issues.append(ReferenceIssue(mark, f"this verse range goes backwards: {last}{mark}{number}"))
            part.verses[-1] = (first, max(number, last))
        else:
            part.verses.append((number, number))
    return text[position:]


def parse_reference(text: str, fmt: ReferenceFormat) -> tuple[list[ReferencePart], list[ReferenceIssue]]:
    """All parts with chapter and verse. Text without chapter and verse ("30-й вірш") gives no parts."""
    text = text.replace("~", " ")  # the USFM no-break space: "1~Цар. 21:1"
    matches = list(_chapter_verses(text, fmt))
    parts: list[ReferencePart] = []
    issues: list[ReferenceIssue] = []
    if not matches:
        return parts, issues
    _, name, chapters = _split_name(text[:matches[0].start()])
    if chapters:
        issues.append(_chapters_question(name, chapters, fmt))
    is_range_end = False
    for index, match in enumerate(matches):
        chapter, verse = int(match.group(1)), int(match.group(5))
        if match.group(3) != fmt.chapter_verse:
            issues.append(_wrong_mark(match.group(3), "between chapter and verse", [fmt.chapter_verse]))
        if is_range_end:
            part = parts[-1]
            if (chapter, verse) < (part.chapter, part.verses[0][0]):
                issues.append(ReferenceIssue(match.group(), f"this chapter range goes backwards: "
                                                            f"{part.chapter}{fmt.chapter_verse}{part.verses[0][0]} "
                                                            f"to {chapter}{fmt.chapter_verse}{verse}"))
            part.end = (chapter, verse)
        else:
            part = ReferencePart(name, chapter, [(verse, verse)])
            parts.append(part)
        following = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        gap = text[match.end():following]
        if part_letter := _VERSE_PART_RE.match(gap):
            gap = gap[part_letter.end():]
        is_range_end, name = False, ""
        if index + 1 == len(matches):
            if not part.end:
                _read_verses(part, gap, fmt, issues)
        elif gap in fmt.chapter_ranges:
            is_range_end = not part.end
        elif gap in fmt.chapter_sequences or gap in fmt.book_sequences:
            pass
        else:
            before_name, name, chapters = _split_gap(gap, fmt)
            if chapters:
                issues.append(_chapters_question(name, chapters, fmt))
            mark = _read_verses(part, before_name, fmt, issues) if not part.end else before_name
            is_range_end = _check_mark_before_chapter(mark, bool(name), bool(part.end), fmt, issues)
    return parts, issues


def _check_mark_before_chapter(mark: str, has_name: bool, has_end: bool, fmt: ReferenceFormat,
                               issues: list[ReferenceIssue]) -> bool:
    """Reports a wrong mark between two references; True if the next reference ends a chapter range."""
    if has_name:
        if fmt.book_sequences and mark not in fmt.book_sequences and not any(ch.isalpha() for ch in mark):
            issues.append(_wrong_mark(mark, "before a book name", fmt.book_sequences))
        return False
    if mark in fmt.chapter_ranges:
        return not has_end
    if mark in fmt.chapter_sequences or mark in fmt.book_sequences:
        return False
    if _is_dash(mark):
        if fmt.chapter_ranges:
            issues.append(_wrong_mark(mark, "in a range of chapters", fmt.chapter_ranges))
        return not has_end
    if fmt.chapter_sequences and not any(ch.isalpha() for ch in mark):
        issues.append(_wrong_mark(mark, "between two references", fmt.chapter_sequences))
    return False
