"""Parse the Publishing Assistant hyphenation list (hyphenatedWords.txt) and apply hyphenation rules.

File format: "#" comment lines, header lines such as `SoftHyphen = "="`, then one word per
line with soft hyphens at the allowed break points ("хо=ди=ти=ме=те"). A leading "*" marks
a line that was reviewed/edited by hand and must be kept as is.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from checker.languages import LanguageProfile

LOCKED_PREFIX = "*"
_HEADER_RE = re.compile(r'^(\w+)\s*=\s*"(.*)"\s*$')

# Consistency: words starting (or ending) with the same AFFIX_LENGTH letters should break
# the same way inside them. A pattern is reported when it is used by at most MINORITY_SHARE
# of the group and the majority pattern has at least MIN_MAJORITY words.
AFFIX_LENGTH = 6
MINORITY_SHARE = 0.2
MIN_MAJORITY = 3
# A word without break points is reported when a part between hard hyphens has at least
# MIN_UNHYPHENATED_LENGTH letters and (if the language profile knows vowels) enough vowels.
MIN_UNHYPHENATED_LENGTH = 7
MIN_UNHYPHENATED_VOWELS = 3


@dataclass(frozen=True)
class HyphenatedWord:
    text: str  # as listed, e.g. "хо=ди=ти=ме=те"
    word: str  # without soft hyphens
    breaks: tuple[int, ...]  # break offsets in `word`
    locked: bool
    line: int

    @property
    def segments(self) -> list[str]:
        bounds = (0, *self.breaks, len(self.word))
        return [self.word[a:b] for a, b in zip(bounds, bounds[1:])]


class HyphenationList:
    def __init__(self, entries: list[HyphenatedWord], soft_hyphen: str = "=", hard_hyphen: str = "-") -> None:
        self.entries = entries
        self.soft_hyphen = soft_hyphen
        self.hard_hyphen = hard_hyphen
        self.by_word = {entry.word.lower(): entry for entry in entries}

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def words(self) -> list[HyphenatedWord]:
        """Single words only; phrases with spaces are skipped by the checks."""
        return [entry for entry in self.entries if " " not in entry.word]


def load_hyphenation(path: Path) -> HyphenationList:
    headers = {"SoftHyphen": "=", "HardHyphen": "-"}
    entries: list[HyphenatedWord] = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip() or line.startswith("#"):
            continue
        header = _HEADER_RE.match(line)
        if header:
            headers[header.group(1)] = header.group(2)
            continue
        soft_hyphen = headers["SoftHyphen"]
        locked = line.startswith(LOCKED_PREFIX)
        text = line[len(LOCKED_PREFIX):] if locked else line
        word, breaks = "", []
        for ch in text:
            if ch == soft_hyphen:
                breaks.append(len(word))
            else:
                word += ch
        if word.strip():
            entries.append(HyphenatedWord(text, word, tuple(breaks), locked, number))
    return HyphenationList(entries, headers["SoftHyphen"], headers["HardHyphen"])


def _letters(text: str) -> str:
    """Lowercase text without combining marks such as stress accents ("ада́м" -> "адам").

    NFC first, so letters with a precomposed form ("й", "ї", "é") stay intact.
    """
    composed = unicodedata.normalize("NFC", text.lower())
    return "".join(ch for ch in composed if not unicodedata.combining(ch))


def word_scripts(word: str) -> set[str]:
    """Scripts of the letters in a word, from Unicode names: {"CYRILLIC"}, {"CYRILLIC", "LATIN"}.

    Modifier letters (category Lm, e.g. the apostrophe "ʼ") belong to no script and are ignored.
    """
    return {
        unicodedata.name(ch, "UNKNOWN").split(" ")[0]
        for ch in word
        if unicodedata.category(ch) in ("Lu", "Ll", "Lt", "Lo")
    }


def rule_violations(
    entry: HyphenatedWord, profile: LanguageProfile, medial_punctuation: frozenset[str]
) -> Iterator[str]:
    """Hyphenation rules broken by the break points of one entry.

    Language independent: a single letter left at a line edge, a break right before
    word-medial punctuation such as an apostrophe. With a language profile: parts without
    a vowel, letters that cannot start a part, glides torn from their vowel.
    """
    scripts = word_scripts(entry.word)
    if len(scripts) > 1:
        yield f"has letters from different alphabets: {' + '.join(sorted(scripts))} (letters that look the same?)"
    segments = entry.segments
    if len(segments) < 2:
        return
    letters = [_letters(segment) for segment in segments]
    vowels = profile.vowels
    # Vowel rules only apply to single-script words written with this language's vowels
    # (skips e.g. English words in a Ukrainian list).
    if len(scripts) == 1 and vowels & set(_letters(entry.word)):
        for segment, plain in zip(segments, letters):
            if plain and not vowels & set(plain):
                yield f"part '{segment}' has no vowel"
    if len(letters[0]) == 1 or len(letters[-1]) == 1:
        yield "one letter stays alone at the end or start of a line"
    for previous, plain in zip(letters, letters[1:]):
        first = plain[:1]
        if first in medial_punctuation or first in profile.no_break_before:
            yield f"a line must not break before '{first}'"
        elif first in profile.glides and previous[-1:] in vowels and plain[1:2] not in vowels:
            yield f"'{first}' must stay with the vowel before it"


def is_unhyphenated(entry: HyphenatedWord, profile: LanguageProfile, hard_hyphen: str = "-") -> bool:
    """No break points although a part between hard hyphens is long enough to need them."""
    if entry.breaks:
        return False
    return any(
        len(part) >= MIN_UNHYPHENATED_LENGTH
        and (not profile.vowels or sum(ch in profile.vowels for ch in part) >= MIN_UNHYPHENATED_VOWELS)
        for part in _letters(entry.word).split(hard_hyphen)
    )


def render(text: str, breaks: Iterable[int], soft_hyphen: str = "=") -> str:
    out = text
    for offset in sorted(breaks, reverse=True):
        out = out[:offset] + soft_hyphen + out[offset:]
    return out


@dataclass(frozen=True)
class AffixInconsistency:
    entry: HyphenatedWord
    side: str  # "prefix" (word beginning) or "suffix" (word ending)
    affix: str  # e.g. "автори" or "тимуть"
    actual: str  # how this entry breaks it, e.g. "авто=ри"
    expected: str  # the majority way, e.g. "ав=то=ри"
    majority_count: int
    group_count: int
    example: str


def _prefix_key(word: str, breaks: tuple[int, ...]) -> tuple[str, tuple[int, ...]]:
    # The last position is skipped: a break there depends on the letters that follow
    # ("свя=ще=ник" vs "свя=щен=на" are both right).
    return word[:AFFIX_LENGTH], tuple(b for b in breaks if b < AFFIX_LENGTH - 1)


def _suffix_key(word: str, breaks: tuple[int, ...]) -> tuple[str, tuple[int, ...]]:
    offset = len(word) - AFFIX_LENGTH
    return word[offset:], tuple(b - offset for b in breaks if b > offset)


def inconsistent_affixes(entries: Iterable[HyphenatedWord]) -> Iterator[AffixInconsistency]:
    """Words sharing the same first (or last) AFFIX_LENGTH letters that break them unlike the majority."""
    entries = [e for e in entries if e.breaks and len(e.word) >= AFFIX_LENGTH + 2]
    for side, key in (("prefix", _prefix_key), ("suffix", _suffix_key)):
        groups: dict[str, dict[tuple[int, ...], list[HyphenatedWord]]] = defaultdict(lambda: defaultdict(list))
        for entry in entries:
            affix, pattern = key(entry.word.lower(), entry.breaks)
            groups[affix][pattern].append(entry)

        for affix, patterns in sorted(groups.items()):
            if len(patterns) < 2:
                continue
            total = sum(len(members) for members in patterns.values())
            majority_pattern, majority = max(patterns.items(), key=lambda item: len(item[1]))
            if len(majority) < MIN_MAJORITY:
                continue
            for pattern, members in patterns.items():
                if pattern == majority_pattern or len(members) > total * MINORITY_SHARE:
                    continue
                for entry in members:
                    yield AffixInconsistency(
                        entry=entry,
                        side=side,
                        affix=affix,
                        actual=render(affix, pattern),
                        expected=render(affix, majority_pattern),
                        majority_count=len(majority),
                        group_count=total,
                        example=majority[0].text,
                    )
