"""Verse numbers in another versification: Paratext .vrs mappings.

A .vrs line "PSA 51:1-19 = PSA 51:3-21" says: verse 51:1 of this versification is verse 51:3 of the Original
versification (org.vrs), and so on. The English versification (eng.vrs, from Paratext / SIL libpalaso, MIT license)
is kept next to this module, because Paratext keeps it inside the program. A project may change it with its own
custom.vrs (same syntax); a custom line replaces the lines of eng.vrs about the same verses.
"""
from __future__ import annotations

import re
from pathlib import Path

Verse = tuple[str, int, int]

ENGLISH_VRS = Path(__file__).with_name("eng.vrs")
CUSTOM_VRS = "custom.vrs"
_REF_RE = re.compile(r"([0-9A-Z]{3})\s+(\d+):(\d+)(?:-(\d+))?$")


def _verses(text: str) -> list[Verse] | None:
    """"PSA 51:1-19" -> [("PSA", 51, 1), ..., ("PSA", 51, 19)]."""
    match = _REF_RE.match(text.strip())
    if not match:
        return None
    book, chapter, first = match.group(1), int(match.group(2)), int(match.group(3))
    last = int(match.group(4) or first)
    return [(book, chapter, verse) for verse in range(first, last + 1)]


def read_mappings(text: str) -> list[tuple[Verse, Verse]]:
    """(verse of this versification, verse of the Original versification) for every mapping line."""
    pairs = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        left, right = (_verses(part) for part in line.split("=", 1))
        if not left or not right:
            continue
        if len(left) == len(right):
            pairs.extend(zip(left, right))
        elif len(left) == 1:          # "PSA 51:0 = PSA 51:1-2": several original verses in one verse
            pairs.extend((left[0], verse) for verse in right)
        elif len(right) == 1:
            pairs.extend((verse, right[0]) for verse in left)
    return pairs


def original_to_project(project: Path) -> dict[Verse, Verse]:
    """Original verse -> verse of a project in the English versification (eng.vrs + the project's custom.vrs)."""
    pairs = read_mappings(ENGLISH_VRS.read_text(encoding="utf-8-sig"))
    custom_path = project / CUSTOM_VRS
    if custom_path.is_file():
        custom = read_mappings(custom_path.read_text(encoding="utf-8-sig"))
        # A custom line replaces every eng.vrs line about the same verse, on either side.
        mine_changed = {mine for mine, _ in custom}
        original_changed = {original for _, original in custom}
        pairs = custom + [(mine, original) for mine, original in pairs
                          if mine not in mine_changed and original not in original_changed]
    mapping: dict[Verse, Verse] = {}
    for mine, original in pairs:
        mapping.setdefault(original, mine)
    return mapping
