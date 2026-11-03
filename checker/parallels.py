"""Parallel passages: the project's own ParallelPassageStatus.xml (written by the Paratext parallel passages tool).

Each <Status> has passageKey "<verse>;<all verses of the parallel group>", a status (F = finished / approved)
and <Content>, the text of the verse when it was approved.

- parallel-changes: an approved verse whose words are different now (changed after the check).
- parallel-differences: two verses of one group, in different books, that differ in only a few words.

A verse range ("MRK 1:7-8") is compared as the text of all its verses; lists ("LUK 6:27-28,35") are skipped.
Words come from the same word rules as the other checks; punctuation is ignored.
The key may use another versification than the text (psalm titles), so when the approved text is very different
from the verse, the nearby verses of the chapter are tried too.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING

from checker import places
from checker.model import WARNING, CheckContext, Finding
from checker.tokens import join_words, split_runs

if TYPE_CHECKING:
    from checker.checks import UsageCounter

PARALLEL_FILE = "ParallelPassageStatus.xml"
CHANGES = "parallel-changes"
DIFFERENCES = "parallel-differences"
APPROVED = "F"
# Below this share of equal words the approved text is "very different" (maybe another verse).
CHANGE_MIN_SIMILARITY = 0.6
# How far the verse numbers of the key may be from the text: psalm titles shift verses by 1-2.
SHIFT_DISTANCE = 3
# Parallel verses are reported when they share at least this share of words and differ in at most N words.
DIFFERENCE_MIN_SIMILARITY = 0.7
DIFFERENCE_MAX_WORDS = 3
SHOWN_WORDS = 8
CONTEXT_CHARS = 90

# "MAT 3:11" or a range "MRK 1:7-8"; lists such as "LUK 6:27-28,35" are not compared.
_SPAN_RE = re.compile(r"([0-9A-Z]{3}) (\d+):(\d+)(?:[-‐‑–](\d+))?")
Span = tuple[str, int, int, int]  # book, chapter, first verse, last verse


@dataclass(frozen=True)
class PassageStatus:
    ref: str                # the verse of this entry, e.g. "MAT 3:11"
    group: tuple[str, ...]  # all verses of the parallel group, e.g. ("MAT 3:11", "MRK 1:7-8", "LUK 3:16")
    status: str
    text: str               # the verse text when it was approved


def load_parallel_status(path: Path) -> list[PassageStatus]:
    entries = []
    for item in ET.parse(path).getroot().iter("Status"):
        parts = [part.strip() for part in (item.get("passageKey") or "").split(";")]
        entries.append(PassageStatus(parts[0], tuple(p for p in parts[1:] if p), item.get("status") or "",
                                     item.findtext("Content") or ""))
    return entries


def _span(ref: str) -> Span | None:
    match = _SPAN_RE.fullmatch(ref)
    if not match:
        return None
    first = int(match.group(3))
    last = int(match.group(4) or first)
    return (match.group(1), int(match.group(2)), first, last) if last >= first else None


def _span_text(usage: UsageCounter, span: Span) -> str | None:
    """Text of all verses of the span; None if one is missing. A "6-7" verse is stored for both numbers: once here."""
    book, chapter, first, last = span
    texts = [usage.verse_texts.get((book, chapter, verse)) for verse in range(first, last + 1)]
    return None if None in texts else " ".join(dict.fromkeys(texts))


def _ref(span: Span) -> str:
    book, chapter, first, last = span
    return f"{chapter}:{first}" if first == last else f"{chapter}:{first}-{last}"


def _words(text: str, ctx: CheckContext) -> list[str]:
    runs = split_runs(text, ctx.is_word_char)
    return [word.text for word in join_words(runs, ctx.settings.word_medial_punctuation)]


def _matcher(a: Sequence[str], b: Sequence[str]) -> SequenceMatcher:
    return SequenceMatcher(None, a, b, autojunk=False)


def _shown(words: Sequence[str]) -> str:
    return " ".join(words[:SHOWN_WORDS]) + (" …" if len(words) > SHOWN_WORDS else "")


def _quoted(words: Sequence[str]) -> str:
    return f"'{_shown(words)}'" if words else "nothing"


def _differences(old: Sequence[str], new: Sequence[str]) -> list[tuple[Sequence[str], Sequence[str]]]:
    return [(old[i1:i2], new[j1:j2]) for op, i1, i2, j1, j2 in _matcher(old, new).get_opcodes() if op != "equal"]


def _context(text: str, words: Sequence[str]) -> str:
    """The verse text around the first of the words."""
    found = text.find(words[0]) if words else -1
    start = max(found - CONTEXT_CHARS // 3, 0) if found >= 0 else 0
    return text[start:start + CONTEXT_CHARS]


def _skipped(ctx: CheckContext, check: str) -> bool:
    if ctx.parallel_passages is None:
        ctx.skipped[check] = (f"Not checked: the project folder has no {PARALLEL_FILE} "
                               f"(no verses were approved in Paratext {places.PARALLEL_PASSAGES}).")
        return True
    return False


def _nearby_span(span: Span, old: list[str], usage: UsageCounter, ctx: CheckContext
                 ) -> tuple[Span, str, list[str]] | None:
    """The same number of verses a little earlier or later in the chapter that is most like the approved text."""
    book, chapter, first, last = span
    best = None
    for distance in range(1, SHIFT_DISTANCE + 1):
        for shift in (-distance, distance):
            moved = (book, chapter, first + shift, last + shift)
            text = _span_text(usage, moved) if first + shift >= 0 else None
            if text is None:
                continue
            words = _words(text, ctx)
            ratio = _matcher(old, words).ratio()
            if ratio >= CHANGE_MIN_SIMILARITY and (best is None or ratio > best[0]):
                best = (ratio, moved, text, words)
    return best[1:] if best else None


def _in_book_order(found: list[tuple[Span, Finding]], usage: UsageCounter) -> Iterator[Finding]:
    order = {book: index for index, book in enumerate(usage.verses)}  # books in file (canonical) order
    found.sort(key=lambda item: (order.get(item[0][0], len(order)), item[0]))
    return (finding for _, finding in found)


def _approved_texts(entries: Sequence[PassageStatus]) -> dict[str, list[str]]:
    """Verse -> its approved texts. A verse is in several entries when Paratext changed the groups later;
    older entries keep older text."""
    texts: dict[str, list[str]] = {}
    for entry in entries:
        if entry.status == APPROVED and _span(entry.ref) and entry.text.strip():
            if entry.text not in texts.setdefault(entry.ref, []):
                texts[entry.ref].append(entry.text)
    return texts


def _changes(ref: str, approved: list[str], usage: UsageCounter, ctx: CheckContext) -> Iterator[tuple[Span, Finding]]:
    span = _span(ref)
    text = _span_text(usage, span)
    if text is None:  # book not checked, or no such verse
        return
    new = _words(text, ctx)
    # The approved text that is most like the verse now is the latest one.
    old = max((_words(item, ctx) for item in approved), key=lambda words: _matcher(words, new).ratio())
    if old == new:
        return
    if _matcher(old, new).ratio() < CHANGE_MIN_SIMILARITY:
        nearby = _nearby_span(span, old, usage, ctx)
        if nearby is None:
            yield span, Finding(span[0], _ref(span), WARNING, CHANGES, ref,
                                "this verse was changed very much after the parallel passage was approved "
                                "(or its verse number is different there)", " ".join(old)[:CONTEXT_CHARS])
            return
        span, text, new = nearby
        if old == new:
            return
    for before, after in _differences(old, new):
        if before and after:
            message = f"'{_shown(before)}' was changed to '{_shown(after)}'"
        elif before:
            message = f"'{_shown(before)}' was removed"
        else:
            message = f"'{_shown(after)}' was added"
        yield span, Finding(span[0], _ref(span), WARNING, CHANGES, _shown(after or before),
                            f"{message} after the parallel passage was approved", _context(text, after or before))


def check_parallel_changes(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    if _skipped(ctx, CHANGES):
        return
    found = [item for ref, approved in _approved_texts(ctx.parallel_passages).items()
             for item in _changes(ref, approved, usage, ctx)]
    yield from _in_book_order(found, usage)


def _pairs(entries: Sequence[PassageStatus]) -> list[tuple[str, str]]:
    """Verses or verse ranges of one group from different books, each pair once, in the order of the file."""
    pairs: dict[frozenset[str], tuple[str, str]] = {}
    for entry in entries:
        verses = [ref for ref in entry.group if _span(ref)]
        for index, first in enumerate(verses):
            for second in verses[index + 1:]:
                if first.split()[0] != second.split()[0]:
                    pairs.setdefault(frozenset((first, second)), (first, second))
    return list(pairs.values())


def check_parallel_differences(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    if _skipped(ctx, DIFFERENCES):
        return
    yield from _in_book_order(list(_differing_pairs(usage, ctx)), usage)


def _differing_pairs(usage: UsageCounter, ctx: CheckContext) -> Iterator[tuple[Span, Finding]]:
    for first, second in _pairs(ctx.parallel_passages):
        span = _span(first)
        text, other_text = _span_text(usage, span), _span_text(usage, _span(second))
        if text is None or other_text is None:
            continue
        words, other_words = _words(text, ctx), _words(other_text, ctx)
        if words == other_words or _matcher(words, other_words).ratio() < DIFFERENCE_MIN_SIMILARITY:
            continue
        differences = _differences(words, other_words)
        if sum(max(len(here), len(there)) for here, there in differences) > DIFFERENCE_MAX_WORDS:
            continue
        shown = "; ".join(f"here {_quoted(here)}, there {_quoted(there)}" for here, there in differences)
        yield span, Finding(span[0], _ref(span), WARNING, DIFFERENCES, second,
                           f"the parallel verse {second} is a little different: {shown}",
                           _context(text, differences[0][0]))
