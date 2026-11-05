"""Verse numbers in another versification: Paratext .vrs mappings.

A .vrs line "PSA 51:1-19 = PSA 51:3-21" says: verse 51:1 of this versification is verse 51:3 of the Original
versification (org.vrs), and so on. The English versification (eng.vrs, the same file as examples/eng.vrs of
github.com/ubsicap/versification_json, MIT license: eng.vrs.LICENSE) is kept next to this module, because Paratext
keeps it inside the program. A project may change it with its own
custom.vrs (same syntax); a custom line replaces the lines of eng.vrs about the same verses.
The other standard versifications of Paratext (lxx, vul, rsc, rso.vrs, same source and license) are kept too: links of
the report send English verse numbers to Paratext.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache
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


# Settings.xml <Versification> -> file of the standard versification ("1" = Original: no file, it is the reference).
STANDARD_FILES = {"2": "lxx.vrs", "3": "vul.vrs", "4": "eng.vrs", "5": "rsc.vrs", "6": "rso.vrs"}
ORIGINAL = "1"


@lru_cache(maxsize=None)
def _to_original(name: str) -> dict[Verse, Verse]:
    """Verse of a standard versification -> Original verse."""
    mapping: dict[Verse, Verse] = {}
    for mine, original in read_mappings(Path(__file__).with_name(name).read_text(encoding="utf-8-sig")):
        # "PSA 113:9 = PSA 115:0" and "PSA 113:9-26 = PSA 115:1-18": a verse of text is verse 1, not the title.
        if mine not in mapping or (mapping[mine][2] == 0 and original[2] and mine[2]):
            mapping[mine] = original
    return mapping


@lru_cache(maxsize=None)
def _original_to_english() -> dict[Verse, Verse]:
    mapping: dict[Verse, Verse] = {}
    for mine, original in read_mappings(ENGLISH_VRS.read_text(encoding="utf-8-sig")):
        mapping.setdefault(original, mine)
    return mapping


def to_english(verse: Verse, versification: str) -> Verse | None:
    """The same verse in the English versification (through Original); None = unknown versification.
    A project's custom.vrs is not used here (report links know only the project name); see project_to_english."""
    if versification == "4":
        return verse
    if versification != ORIGINAL:
        if versification not in STANDARD_FILES:
            return None
        verse = _to_original(STANDARD_FILES[versification]).get(verse, verse)
    return _original_to_english().get(verse, verse)


@lru_cache(maxsize=8)
def _project_to_original(versification: str, custom_text: str) -> dict[Verse, Verse]:
    """Verse of a project -> Original verse: its standard versification with the lines of its custom.vrs, which
    replace the standard lines about the same verse on either side."""
    pairs = []
    if versification != ORIGINAL:
        pairs = read_mappings(Path(__file__).with_name(STANDARD_FILES[versification]).read_text(encoding="utf-8-sig"))
    custom = read_mappings(custom_text)
    mine_changed = {mine for mine, _ in custom}
    original_changed = {original for _, original in custom}
    mapping: dict[Verse, Verse] = {}
    for mine, original in custom + [(mine, original) for mine, original in pairs
                                    if mine not in mine_changed and original not in original_changed]:
        # A verse of text is verse 1, not the title ("PSA 113:9 = PSA 115:0" and "PSA 113:9-26 = PSA 115:1-18").
        if mine not in mapping or (mapping[mine][2] == 0 and original[2] and mine[2]):
            mapping[mine] = original
    return mapping


def project_to_original(project: Path, versification: str) -> Callable[[Verse], Verse] | None:
    """A function: verse of the project -> the same verse in the Original versification, with the project's
    custom.vrs (Settings.xml without <Versification> = "4", English). None = unknown versification.

    Two projects are compared in Original numbers: going on to English is not exact, because eng.vrs has lines such
    as "PSA 13:0-5 = PSA 13:1-6", which turn English 13:6 into 13:5 on the way back."""
    versification = versification or "4"
    if versification != ORIGINAL and versification not in STANDARD_FILES:
        return None
    custom_path = project / CUSTOM_VRS
    custom_text = custom_path.read_text(encoding="utf-8-sig") if custom_path.is_file() else ""
    to_original = _project_to_original(versification, custom_text)
    return lambda verse: to_original.get(verse, verse)
