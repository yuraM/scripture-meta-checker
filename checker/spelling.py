"""Parse the Paratext spelling list (SpellingStatus.xml)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import cached_property, lru_cache
from pathlib import Path

from checker.tokens import single_edit

STATE_RIGHT = "R"
STATE_WRONG = "W"
# Approved words shorter than this get no "similar" suggestions (too many accidental neighbours).
MIN_SUGGESTION_LENGTH = 4
MAX_SUGGESTIONS = 3


@dataclass(frozen=True)
class SpellingEntry:
    word: str
    state: str
    # Required spellings with capitalization, e.g. "Аарона" for the key "аарона".
    specific_cases: tuple[str, ...] = ()
    corrections: tuple[str, ...] = ()


class SpellingList:
    def __init__(self, entries: dict[str, SpellingEntry]) -> None:
        self.entries = entries

    def __len__(self) -> int:
        return len(self.entries)

    def lookup(self, word: str) -> SpellingEntry | None:
        """Find an entry by the exact word first, then by its lowercase form (the usual key)."""
        return self.entries.get(word) or self.entries.get(word.lower())

    @cached_property
    def _by_deletion(self) -> dict[str, list[str]]:
        """Approved lowercase words keyed by themselves and by each one-letter deletion."""
        index: dict[str, list[str]] = {}
        for key, entry in self.entries.items():
            word = key.lower()
            if entry.state != STATE_RIGHT or len(word) < MIN_SUGGESTION_LENGTH or " " in word:
                continue
            for variant in {word, *(word[:i] + word[i + 1:] for i in range(len(word)))}:
                index.setdefault(variant, []).append(word)
        return index

    def similar(self, word: str) -> tuple[str, ...]:
        """Approved words one edit away (substitution, transposition, missing or extra letter)."""
        return _similar(self, word.lower())


@lru_cache(maxsize=100_000)
def _similar(spelling: SpellingList, word: str) -> tuple[str, ...]:
    index = spelling._by_deletion
    candidates = dict.fromkeys(
        found for key in (word, *(word[:i] + word[i + 1:] for i in range(len(word))))
        for found in index.get(key, ())
    )
    return tuple(c for c in candidates if single_edit(word, c))[:MAX_SUGGESTIONS]


def load_spelling_status(path: Path) -> SpellingList:
    root = ET.parse(path).getroot()
    entries: dict[str, SpellingEntry] = {}
    for element in root.iter("Status"):
        word = element.get("Word")
        if not word:
            continue
        entries[word] = SpellingEntry(
            word=word,
            state=element.get("State", ""),
            specific_cases=tuple(e.text for e in element.findall("SpecificCase") if e.text),
            corrections=tuple(e.text for e in element.findall("Correction") if e.text),
        )
    return SpellingList(entries)
