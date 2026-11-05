"""divine-name check: the divine name without \\nd in a verse where translations have it.

`nd_verses.txt` (kept next to this module and bundled into the exe) lists the verses, in the English versification,
where an English base translation marks the divine name (LORD) with \\nd: only verse numbers, no text. A project's
verse is converted to English (versification.to_english) and looked up there.

Words of the project itself say which word is the divine name: a word in \\nd in at least MIN_INSIDE places and
MIN_SHARE of its places. Such a word without \\nd in a listed verse that has no \\nd at all is reported. A verse
without such a word is not reported: translations often say "he" where the base translation says "the LORD".
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from checker.model import CONTEXT_WIDTH, WARNING, Finding
from checker.structure import verse_range
from checker.versification import Verse, to_english

ND_VERSES = Path(__file__).with_name("nd_verses.txt")
MIN_INSIDE = 20   # the word is in \nd at least this often
MIN_SHARE = 0.8   # and in at least this part of its places
ENGLISH = "4"     # Settings.xml without <Versification>: Paratext uses English

Location = tuple[str, str]  # (book, "chapter:verse")
_LINE_RE = re.compile(r"([0-9A-Z]{3}) (\d+):([\d,-]+)$")


@lru_cache(maxsize=1)
def nd_verses(path: Path = ND_VERSES) -> frozenset[Verse]:
    """"GEN 2:4-5,7" -> {("GEN", 2, 4), ("GEN", 2, 5), ("GEN", 2, 7)}."""
    verses = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _LINE_RE.match(line.strip())
        if not match:
            continue
        book, chapter = match.group(1), int(match.group(2))
        for part in match.group(3).split(","):
            first, _, last = part.partition("-")
            verses.update((book, chapter, verse) for verse in range(int(first), int(last or first) + 1))
    return frozenset(verses)


def _verses(location: Location) -> list[Verse]:
    """("GEN", "4:6-7") -> [("GEN", 4, 6), ("GEN", 4, 7)]."""
    book, ref = location
    chapter, _, verse = ref.partition(":")
    numbers = verse_range(verse)
    if not chapter.isdigit() or not numbers:
        return []
    return [(book, int(chapter), number) for number in range(numbers[0], numbers[1] + 1)]


def _context(text: str, word: str) -> str | None:
    """Text around the word written as a name: not with a small letter ("tu señor" is a man). None = no such word."""
    for match in re.finditer(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.IGNORECASE):
        if not match.group()[0].islower():
            return text[max(match.start() - CONTEXT_WIDTH, 0):match.end() + CONTEXT_WIDTH]
    return None


def check_divine_name(
    style_refs: dict[tuple[str, str], tuple[list[Location], list[Location]]],
    verse_texts: dict[Verse, str],
    versification: str,
) -> Iterator[Finding]:
    """`style_refs`: (marker, lowercase word) -> places inside / outside the style (UsageCounter.style_refs)."""
    versification = versification or ENGLISH
    listed = nd_verses()
    with_nd = {location for (marker, _), (inside, _) in style_refs.items() if marker == "nd" for location in inside}
    for (marker, word), (inside, outside) in sorted(style_refs.items()):
        if marker != "nd" or len(inside) < MIN_INSIDE or len(inside) < MIN_SHARE * (len(inside) + len(outside)):
            continue
        reported = set()
        for location in outside:
            if location in with_nd or location in reported:
                continue
            verses = _verses(location)
            if not any(to_english(verse, versification) in listed for verse in verses):
                continue
            text = " ".join(verse_texts[verse] for verse in verses if verse in verse_texts)
            context = _context(text, word)
            if context is None:
                continue
            reported.add(location)
            share = round(100 * len(inside) / (len(inside) + len(outside)))
            yield Finding(location[0], location[1], WARNING, "divine-name", word,
                          f"'{word}' is not in \\nd here, but in {share}% of the places it is "
                          f"({len(inside)} of {len(inside) + len(outside)}), and in this verse other translations "
                          "have the name of God (LORD) in \\nd", context)
