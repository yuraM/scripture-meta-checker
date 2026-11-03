"""Split segment text into word runs, punctuation runs, words and graphemes."""
from __future__ import annotations

import re
import sys
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from checker.settings import SPACE_PLACEHOLDER


def _mark_ranges() -> str:
    """Regex class body of all combining marks (Unicode categories Mn, Mc, Me)."""
    ranges, start = [], None
    for code in range(sys.maxunicode + 2):
        is_mark = code <= sys.maxunicode and unicodedata.category(chr(code))[0] == "M"
        if is_mark and start is None:
            start = code
        elif not is_mark and start is not None:
            ranges.append(f"{re.escape(chr(start))}-{re.escape(chr(code - 1))}")
            start = None
    return "".join(ranges)


# One letter of a word in a regex. Python's \w has no combining marks, but many scripts write vowels
# with them (Devanagari "यशा" ends with the vowel sign U+093E), so a name without them would be cut.
LETTER = rf"(?:[^\W\d_]|[{_mark_ranges()}])"


@dataclass(frozen=True)
class Run:
    text: str
    start: int
    is_word: bool

    @property
    def end(self) -> int:
        return self.start + len(self.text)


def make_word_char_predicate(punctuation_characters: frozenset[str]) -> Callable[[str], bool]:
    """Letters, marks and digits form words, except characters declared as punctuation (e.g. "ʼ")."""

    def is_word_char(ch: str) -> bool:
        return ch not in punctuation_characters and unicodedata.category(ch)[0] in "LMN"

    return is_word_char


def split_runs(text: str, is_word_char: Callable[[str], bool]) -> list[Run]:
    """Split text into alternating word runs and non-word runs (punctuation and whitespace)."""
    runs: list[Run] = []
    start = 0
    for index in range(1, len(text) + 1):
        if index == len(text) or is_word_char(text[index]) != is_word_char(text[start]):
            runs.append(Run(text[start:index], start, is_word_char(text[start])))
            start = index
    return runs


def join_words(runs: list[Run], medial_punctuation: frozenset[str]) -> list[Run]:
    """Merge word runs joined by word-medial punctuation: "Кір" "ʼ" "ят" "-" "Арбу" -> "Кірʼят-Арбу"."""
    words: list[Run] = []
    index = 0
    while index < len(runs):
        run = runs[index]
        if not run.is_word:
            index += 1
            continue
        start, end = run.start, run.end
        parts = [run.text]
        while (
            index + 2 < len(runs)
            and all(ch in medial_punctuation for ch in runs[index + 1].text)
            and runs[index + 2].is_word
        ):
            parts += [runs[index + 1].text, runs[index + 2].text]
            end = runs[index + 2].end
            index += 2
        words.append(Run("".join(parts), start, True))
        index += 1
    return words


def punctuation_pattern(run: Run, text_length: int) -> str:
    """Render a non-word run the way Settings.xml lists it: whitespace and paragraph edges become "_"."""
    pattern = "".join(SPACE_PLACEHOLDER if ch.isspace() else ch for ch in run.text)
    if run.start == 0:
        pattern = SPACE_PLACEHOLDER + pattern
    if run.end == text_length:
        pattern += SPACE_PLACEHOLDER
    return pattern


def graphemes(text: str) -> Iterator[tuple[int, str]]:
    """Yield (offset, cluster) where a cluster is a base character plus its combining marks."""
    start = 0
    for index in range(1, len(text) + 1):
        if index == len(text) or not unicodedata.combining(text[index]):
            yield start, text[start:index]
            start = index


def single_edit(a: str, b: str) -> tuple[str, int] | None:
    """The one edit turning a into b ("substitution", "transposition", "insertion") and its index."""
    if a == b:
        return None
    index = 0
    while index < min(len(a), len(b)) and a[index] == b[index]:
        index += 1
    if len(a) == len(b):
        if a[index + 1:] == b[index + 1:]:
            return "substitution", index
        if a[index + 2:] == b[index + 2:] and a[index:index + 2] == b[index:index + 2][::-1]:
            return "transposition", index
        return None
    shorter, longer = sorted((a, b), key=len)
    if len(longer) - len(shorter) == 1 and shorter[index:] == longer[index + 1:]:
        return "insertion", index
    return None
