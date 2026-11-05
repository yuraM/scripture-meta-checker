"""divine-name check: the divine name without \\nd in a verse where translations have it.

`nd_verses.txt` (kept next to this module and bundled into the exe) lists the verses where an English base translation
marks the divine name (LORD) with \\nd and how many times: only verse numbers, no text, in the Original versification
(the base translation's own custom.vrs applied). A project's verse is converted to Original with its versification and
its custom.vrs (versification.project_to_original) and looked up there.

Words of the project itself say which word is the divine name: a word in \\nd in at least MIN_INSIDE places and
MIN_SHARE of its places. Such a word without \\nd (not written small) in a verse that has fewer \\nd than the map says
is reported: "\\nd Herren\\nd* … Så säger Herren" where the map has 2. A verse with fewer \\nd but without such a word
is not reported: translations often say "he" where the base translation says "the LORD". More \\nd than the map is
not reported either: translations often repeat the name where the base translation has "he".
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from checker.model import CONTEXT_WIDTH, WARNING, Finding
from checker.structure import verse_range
from checker.versification import Verse

ND_VERSES = Path(__file__).with_name("nd_verses.txt")
MIN_INSIDE = 20   # the word is in \nd at least this often
MIN_SHARE = 0.8   # and in at least this part of its places

Location = tuple[str, str]  # (book, "chapter:verse")
_LINE_RE = re.compile(r"([0-9A-Z]{3}) (\d+):([\d,*-]+)$")


@dataclass
class VerseNd:
    """The scripture text of one verse: how many \\nd, and its words without \\nd that are not written small."""
    count: int = 0
    plain: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def nd_verses(path: Path = ND_VERSES) -> dict[Verse, int]:
    """"GEN 2:4-5,7*2" -> {("GEN", 2, 4): 1, ("GEN", 2, 5): 1, ("GEN", 2, 7): 2}."""
    verses: dict[Verse, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _LINE_RE.match(line.strip())
        if not match:
            continue
        book, chapter = match.group(1), int(match.group(2))
        for part in match.group(3).split(","):
            numbers, _, count = part.partition("*")
            first, _, last = numbers.partition("-")
            for verse in range(int(first), int(last or first) + 1):
                verses[(book, chapter, verse)] = int(count or 1)
    return verses


def _verses(location: Location) -> list[Verse]:
    """("GEN", "4:6-7") -> [("GEN", 4, 6), ("GEN", 4, 7)]."""
    book, ref = location
    chapter, _, verse = ref.partition(":")
    numbers = verse_range(verse)
    if not chapter.isdigit() or not numbers:
        return []
    return [(book, int(chapter), number) for number in range(numbers[0], numbers[1] + 1)]


def _context(text: str, word: str) -> str:
    match = re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text)
    if not match:
        return text[:2 * CONTEXT_WIDTH]
    return text[max(match.start() - CONTEXT_WIDTH, 0):match.end() + CONTEXT_WIDTH]


def usual_nd_words(style_refs: dict[tuple[str, str], tuple[list[Location], list[Location]]]) -> dict[str, str]:
    """Lowercase words the project nearly always puts in \\nd -> "in \\nd in 85% of the places (4693 of 5509)"."""
    usual = {}
    for (marker, word), (inside, outside) in style_refs.items():
        total = len(inside) + len(outside)
        if marker == "nd" and len(inside) >= MIN_INSIDE and len(inside) >= MIN_SHARE * total:
            usual[word] = f"in {round(100 * len(inside) / total)}% of the places it is ({len(inside)} of {total})"
    return usual


def check_divine_name(
    style_refs: dict[tuple[str, str], tuple[list[Location], list[Location]]],
    places: dict[Location, VerseNd],
    verse_texts: dict[Verse, str],
    to_original: Callable[[Verse], Verse],
) -> Iterator[Finding]:
    """`style_refs`: (marker, lowercase word) -> places inside / outside the style (UsageCounter.style_refs);
    `places`: \\nd count and plain words per verse (UsageCounter.nd_places); `to_original`: project verse -> Original."""
    usual = usual_nd_words(style_refs)
    if not usual:
        return
    listed = nd_verses()
    for location, place in places.items():
        word = next((word for word in place.plain if word.lower() in usual), None)
        if word is None:
            continue
        verses = _verses(location)
        expected = sum(listed.get(to_original(verse), 0) for verse in verses)
        if place.count >= expected:
            continue
        text = " ".join(verse_texts[verse] for verse in verses if verse in verse_texts)
        here = "there is no \\nd here" if not place.count else f"here only {place.count}"
        yield Finding(location[0], location[1], WARNING, "divine-name", word.lower(),
                      f"'{word}' is not in \\nd here, but {usual[word.lower()]}. In this verse other translations "
                      f"have the name of God (LORD) in \\nd {expected} times; {here}", _context(text, word))
