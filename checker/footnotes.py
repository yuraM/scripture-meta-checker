"""footnotes check: footnotes built differently from similar footnotes of the same project.

No language data: the project's own notes are the rule. The "formula" of a note is its fixed text before the first
quote or reference marker, with numbers as N, plus that marker: "Lit.: \\fqa" in
`\\f + \\fr 3:5 \\ft Lit.: \\fqa the sons of God\\f*`. Formulas used by many notes show the usual form; a note that
is nearly the same but not quite is reported.

The notes are read from the raw file (the markers are needed); `UsageCounter.add_source` collects them for the
checked books, and the check runs once for the project.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from checker.model import ERROR, WARNING, Finding
from checker.usfm import remove_attributes

CHECK = "footnotes"
_NOTE_RE = re.compile(r"\\f\s+\S+(.*?)\\f\*", re.S)
_TOKEN_RE = re.compile(r"\\c\s+(\d+)|\\v\s+([0-9][^\s\\]*)|\\f\s")
_MARKER_RE = re.compile(r"\\\+?([a-z]+\d*)(\*?)[ \t]?")
_WORD_RE = re.compile(r"\w+")
# "1,000", "4 1⁄2", "2.9" are one number.
_NUMBER_RE = re.compile(r"\d+(?:\s?[^\w\s]?\d+)*")
_REM_RE = re.compile(r"^\\(?:rem|id)\b.*$", re.M)

TEXT_MARKERS = frozenset({"ft", "fp"})  # plain text of the note
SKIPPED_MARKERS = frozenset({"fr", "fv"})  # reference of the note, verse number inside a quote
QUOTE_TAGS = frozenset({"fq", "fqa"})  # W1 and W2 compare these two

# E1: a formula one character (or only punctuation) away from a much more frequent one.
E1_MIN_USUAL, E1_RATIO = 20, 10
E1_SHORT_WORD = 2  # a changed whole word of at most 2 letters is a unit (kg / m), not a typing mistake
# E2: the end mark of a note, when nearly all notes have one.
E2_MIN_NOTES, E2_SHARE = 100, 0.99
# W1: the quote marker after a formula, when nearly all notes with the formula use another one.
W1_MIN_NOTES, W1_MAX_SHARE = 12, 0.1
# W2: an alternative reading (\fqa) that is word for word in the verse.
W2_MIN_WORDS = 3
# W4: a formula with one other word than a more frequent one.
W4_MIN_USUAL, W4_RATIO = 5, 3


@dataclass(frozen=True)
class Note:
    book: str
    ref: str  # chapter:verse where the note stands
    parts: tuple[tuple[str, str], ...]  # (marker, text): "ft" for plain text
    raw: str  # the note as in the file, for the context of a finding

    @property
    def text(self) -> str:
        """The text of the note without its reference and markers."""
        return " ".join(" ".join(text for marker, text in self.parts if marker != "fr").split())

    @property
    def formula(self) -> tuple[str, str]:
        """(fixed text before the first quote / reference marker with numbers as N, that marker or "")."""
        words = []
        for marker, text in self.parts:
            if marker in SKIPPED_MARKERS:
                continue
            if marker not in TEXT_MARKERS:
                return _norm(" ".join(words)), marker
            words.append(text)
        return _norm(" ".join(words)), ""

    def tagged_text(self, tag: str) -> str:
        return " ".join(text for marker, text in self.parts if marker == tag)


def _norm(text: str) -> str:
    return _NUMBER_RE.sub("N", " ".join(text.split()))


def _parts(body: str) -> tuple[tuple[str, str], ...]:
    """\\fr 3:5 \\ft Lit.: \\fqa the sons\\fqa* of God -> (fr, 3:5) (ft, Lit.:) (fqa, the sons) (ft, of God)."""
    parts, marker, last = [], "ft", 0
    for match in _MARKER_RE.finditer(body):
        parts.append((marker, body[last:match.start()]))
        marker = "ft" if match.group(2) else match.group(1)  # a closing marker returns to the plain text
        last = match.end()
    parts.append((marker, body[last:]))
    return tuple((m, " ".join(t.split())) for m, t in parts if t.strip())


def read_notes(book: str, content: str) -> list[Note]:
    """The footnotes (\\f … \\f*) of a book file, with the chapter:verse they stand in."""
    content = remove_attributes(_REM_RE.sub("", content))
    notes, chapter, verse = [], "0", "0"
    for token in _TOKEN_RE.finditer(content):
        if token.group(1):
            chapter, verse = token.group(1), "0"
        elif token.group(2):
            verse = token.group(2)
        else:
            match = _NOTE_RE.match(content, token.start())
            if match:
                notes.append(Note(book, f"{chapter}:{verse}", _parts(match.group(1)), match.group(0)))
    return notes


def _strip_punctuation(text: str) -> str:
    return " ".join("".join(ch for ch in text if not unicodedata.category(ch).startswith("P")).split())


def _strip_end(text: str) -> str:
    while text and unicodedata.category(text[-1]).startswith("P"):
        text = text[:-1]
    return text.rstrip()


def _one_edit(a: str, b: str) -> bool:
    """a and b differ by one inserted, deleted or replaced character."""
    if abs(len(a) - len(b)) > 1 or a == b:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i + (len(a) == len(b)):] == b[i + 1:]


def _changed_words(a: str, b: str) -> tuple[list[str], list[str]] | None:
    """The words that differ, when a and b have the same number of words; else None."""
    wa, wb = a.split(), b.split()
    if len(wa) != len(wb):
        return None
    pairs = [(x, y) for x, y in zip(wa, wb) if x != y]
    return [x for x, _ in pairs], [y for _, y in pairs]


def _letters(word: str) -> int:
    return sum(ch.isalpha() for ch in word)


def _is_unit_change(a: str, b: str) -> bool:
    """Only one short whole word is different ("About N kg" / "About N m"): a real difference, not a typo."""
    changed = _changed_words(a, b)
    if not changed or len(changed[0]) != 1:
        return False
    x, y = changed[0][0], changed[1][0]
    return 0 < _letters(x) <= E1_SHORT_WORD and 0 < _letters(y) <= E1_SHORT_WORD and x.strip(".") != y.strip(".")


def _ends_well(text: str, final: frozenset[str]) -> tuple[bool, str]:
    """(the note ends with an end mark, its last sign); closing quotes and brackets are skipped."""
    text = text.rstrip()
    while text and (unicodedata.category(text[-1]) in ("Pe", "Pf") or text[-1] in "'\""):
        text = text[:-1].rstrip()
    last = text[-1:]
    return (last in final or last == "…"), last


def _shown(text: str, tag: str) -> str:
    return f"{text} \\{tag}" if tag else text


def check_footnotes(notes: list[Note], final_marks: frozenset[str],
                    verse_texts: dict[tuple[str, int, int], str]) -> list[Finding]:
    findings: list[Finding] = []
    if not notes:
        return findings
    formulas = Counter(note.formula for note in notes)
    notes_of: dict[tuple[str, str], list[Note]] = {}
    for note in notes:
        notes_of.setdefault(note.formula, []).append(note)

    def add(note: Note, severity: str, item: str, message: str) -> None:
        findings.append(Finding(note.book, note.ref, severity, CHECK, item, message, note.raw))

    # E1 / W4: a formula nearly the same as a much more frequent one with the same marker.
    # Only frequent formulas can be the usual form: the others are compared with them.
    frequent: dict[str, list[tuple[str, int, str]]] = {}
    for (text, tag), count in formulas.items():
        if text and count >= min(E1_MIN_USUAL, W4_MIN_USUAL):
            frequent.setdefault(tag, []).append((text, count, _strip_punctuation(text)))
    for (text, tag), count in formulas.items():
        if not text:
            continue
        bare = _strip_punctuation(text)
        # A note without a marker is a whole explanation ("about 1 meter" / "about 3 meters"): only a difference in
        # punctuation inside it counts; a missing end mark is left to E2.
        typo = next((usual for usual, usual_count, usual_bare in frequent.get(tag, [])
                     if usual != text and usual_count >= E1_MIN_USUAL and usual_count >= E1_RATIO * count
                     and (bare == usual_bare if not tag else _one_edit(text, usual) or bare == usual_bare)
                     and not (not tag and _strip_end(text) == _strip_end(usual))
                     and not _is_unit_change(text, usual)), None)
        if typo:
            for note in notes_of[(text, tag)]:
                add(note, ERROR, text, f"note starts '{_shown(text, tag)}', but {formulas[(typo, tag)]} notes start "
                                       f"'{_shown(typo, tag)}': a typing mistake?")
            continue
        # A note without any marker is a whole explanation, not a formula: different words are its content.
        words = text.split()
        other = tag and next((usual for usual, usual_count, _ in frequent.get(tag, [])
                              if usual != text and usual_count >= W4_MIN_USUAL and usual_count >= W4_RATIO * count
                              and (changed := _changed_words(text, usual)) and len(changed[0]) == 1
                              and words[0] == usual.split()[0] and not _is_unit_change(text, usual)), None)
        if other:
            for note in notes_of[(text, tag)]:
                add(note, WARNING, text, f"note starts '{_shown(text, tag)}', but {formulas[(other, tag)]} notes "
                                         f"start '{_shown(other, tag)}' (one word is different)")

    # E2: the end mark of the note.
    endings = [(note, *_ends_well(note.text, final_marks)) for note in notes]
    good = sum(ok for _, ok, _ in endings)
    if len(notes) >= E2_MIN_NOTES and good >= E2_SHARE * len(notes):
        for note, ok, last in endings:
            if not ok:
                add(note, ERROR, last or note.raw,
                    f"note does not end with an end mark such as '.', but {good} of {len(notes)} notes do")

    # W1: the quote marker after a formula. W2: \fqa that stands in the verse where the formula usually has \fq.
    tags: dict[str, Counter[str]] = {}
    for (text, tag), count in formulas.items():
        if text:
            tags.setdefault(text, Counter())[tag] += count
    usual_tag = {text: counts.most_common(1)[0] for text, counts in tags.items()}
    totals = {text: sum(counts.values()) for text, counts in tags.items()}
    # Formulas usually followed by a quote marker, longest first: a note that starts so but has no marker lacks it.
    quoted = sorted((text for text, (tag, _) in usual_tag.items() if tag in QUOTE_TAGS), key=len, reverse=True)
    untagged: dict[str, list[Note]] = {}
    for note in notes:
        if not note.formula[1]:
            whole = _norm(note.text)
            start = next((f for f in quoted if whole.startswith(f + " ")), None)
            if start:
                untagged.setdefault(start, []).append(note)
    for start, missing in untagged.items():
        with_tag = sum(count for tag, count in tags[start].items() if tag in QUOTE_TAGS)
        total = with_tag + len(missing)
        if total >= W1_MIN_NOTES and len(missing) <= W1_MAX_SHARE * total:
            shown = " or ".join(f"\\{tag}" for tag, _ in tags[start].most_common() if tag in QUOTE_TAGS)
            for note in missing:
                add(note, WARNING, start, f"after '{start}' the note has no {shown}, but {with_tag} of {total} "
                                          "notes that start so have it")
    for note in notes:
        text, tag = note.formula
        if not tag:
            continue
        if text not in usual_tag:
            continue
        common, common_count = usual_tag[text]
        total = totals[text]
        if total < W1_MIN_NOTES:
            continue
        if tag == "fqa" and common == "fq" and _in_verse(note, verse_texts):
            alternative = note.tagged_text("fqa")
            add(note, WARNING, alternative,
                f"the other reading (\\fqa) '{alternative}' is in the verse word for word: should it be \\fq? "
                f"After '{text}', {common_count} of {total} notes have \\fq")
        elif tag != common and {tag, common} <= QUOTE_TAGS and tags[text][tag] <= W1_MAX_SHARE * total:
            add(note, WARNING, text, f"after '{text}' the note has \\{tag}, but {common_count} of {total} notes "
                                     f"like it have \\{common}")
    return findings


def _in_verse(note: Note, verse_texts: dict[tuple[str, int, int], str]) -> bool:
    """The \\fqa text of the note (at least W2_MIN_WORDS words) stands word for word in the verse of the note."""
    words = [w.casefold() for w in _WORD_RE.findall(note.tagged_text("fqa"))]
    chapter, _, verse = note.ref.partition(":")
    verse_number = re.match(r"\d+", verse)
    if len(words) < W2_MIN_WORDS or not chapter.isdigit() or not verse_number:
        return False
    verse_text = verse_texts.get((note.book, int(chapter), int(verse_number.group())), "")
    verse_words = [w.casefold() for w in _WORD_RE.findall(verse_text)]
    return any(verse_words[i:i + len(words)] == words for i in range(len(verse_words) - len(words) + 1))
