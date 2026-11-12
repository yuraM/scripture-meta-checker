"""Signs written in the rare way of the project (Unit 3): the text decides, nothing is changed.

- digit-systems: digits of another system than most numbers of the project (`۲۷` among `27`, `1` among `၁`). Digits
  next to letters of their own script are another language (`Copyright 1985` in a Myanmar text) and are skipped.
- fractions: `1/2` written with a slash when the project writes most fractions with the fraction slash `⁄` (U+2044).
  Only real fractions (the first number smaller: `587/6` is a year).
- apostrophes: a sign between two letters (`'` `’` `ʼ` `ʻ`) that is not the one the project nearly always uses there.
Tried and dropped (2026-11-12): a quote closed at a paragraph end and opened again in the next paragraph (same
speaker?) - 20-456 per project, nearly all dialogue with another speaker.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterator

from checker.model import WARNING, Analysis, CheckContext, Finding
from checker.structure import PERIPHERAL_BOOKS
from checker.usfm import Segment

MIN_USUAL = 20  # the usual form is used at least this often
MIN_SHARE = 0.9  # and in at least this part of the places
APOSTROPHES = "'’ʼʻ"
FRACTION_RE = re.compile(r"(?<![\d/⁄])(\d+)([/⁄])(\d+)(?![\d/⁄])")
NUMBER_RE = re.compile(r"\d+")
SCRIPT_CONTEXT = 30  # characters on each side looked at for letters of the digits' own script


def _finding(segment: Segment, offset: int, length: int, check: str, item: str, message: str) -> Finding:
    return Analysis(segment, [], []).finding(offset, length, WARNING, check, item, message)


def _digit_script(ch: str) -> str:
    """'DIGIT ONE' -> LATIN, 'EXTENDED ARABIC-INDIC DIGIT ONE' -> ARABIC, 'MYANMAR DIGIT ONE' -> MYANMAR."""
    words = unicodedata.name(ch, "").split(" DIGIT")[0].split()
    words = [word for word in words if word not in ("EXTENDED", "FULLWIDTH", "MATHEMATICAL")]
    return words[-1].split("-")[0] if words else "LATIN"


def _letter_scripts(text: str) -> set[str]:
    return {unicodedata.name(ch, "").split()[0] for ch in text if ch.isalpha() and unicodedata.name(ch, "")}


def _system(number: str) -> str:
    """The digits of '27' -> '0123456789' as a name: the zero of the system."""
    return chr(ord(number[0]) - unicodedata.decimal(number[0]))


EXTRA_MATERIAL = frozenset(book for book in PERIPHERAL_BOOKS if book.startswith("XX"))


def check_digit_systems(segments: list[Segment], ctx: CheckContext) -> Iterator[Finding]:
    places: list[tuple[Segment, re.Match[str], str]] = []
    for segment in segments:
        for match in NUMBER_RE.finditer(segment.text):
            places.append((segment, match, _system(match.group())))
    counts = Counter(system for _, _, system in places)
    if not counts:
        return
    usual, usual_count = counts.most_common(1)[0]
    if usual_count < MIN_USUAL or usual_count < sum(counts.values()) * MIN_SHARE:
        return
    example = next(match.group() for _, match, system in places if system == usual)
    for segment, match, system in places:
        if system == usual:
            continue
        around = segment.text[max(match.start() - SCRIPT_CONTEXT, 0):match.end() + SCRIPT_CONTEXT]
        if _digit_script(match.group()[0]) in _letter_scripts(around):
            continue  # a number inside text of another language
        number = match.group()
        usual_form = "".join(chr(ord(usual) + unicodedata.decimal(ch)) for ch in number)
        yield _finding(segment, match.start(), len(number), "digit-systems", number,
                       f"'{number}' uses other digits than {usual_count} of {sum(counts.values())} numbers of the "
                       f"project (like '{example}'): write '{usual_form}'")


def check_fractions(segments: list[Segment], ctx: CheckContext) -> Iterator[Finding]:
    places = []
    for segment in segments:
        for match in FRACTION_RE.finditer(segment.text):
            if int(match.group(1)) < int(match.group(3)):
                places.append((segment, match))
    with_slash = [(s, m) for s, m in places if m.group(2) == "/"]
    with_fraction_slash = len(places) - len(with_slash)
    if not with_slash or with_fraction_slash <= len(with_slash):
        return  # the project writes fractions with "/" (or has no fraction slash): its choice
    for segment, match in with_slash:
        fraction = match.group()
        better = f"{match.group(1)}⁄{match.group(3)}"
        yield _finding(segment, match.start(), len(fraction), "fractions", fraction,
                       f"change '{fraction}' to '{better}': {with_fraction_slash} of {len(places)} fractions of the "
                       "project use the fraction slash ⁄ (U+2044)")


def check_apostrophes(segments: list[Segment], ctx: CheckContext) -> Iterator[Finding]:
    places = []
    for segment in segments:
        if segment.book in EXTRA_MATERIAL:  # extra material is often in another language (English "God's")
            continue
        text = segment.text
        for index in range(1, len(text) - 1):
            if text[index] in APOSTROPHES and text[index - 1].isalpha() and text[index + 1].isalpha():
                places.append((segment, index))
    counts = Counter(segment.text[index] for segment, index in places)
    if len(counts) < 2:
        return
    usual, usual_count = counts.most_common(1)[0]
    if usual_count < MIN_USUAL or usual_count < len(places) * MIN_SHARE:
        return
    for segment, index in places:
        sign = segment.text[index]
        if sign == usual:
            continue
        word = re.search(r"\w+$", segment.text[:index]).group() + sign + re.match(r"\w+", segment.text[index + 1:]).group()
        yield _finding(segment, index, 1, "apostrophes", sign,
                       f"change '{sign}' to '{usual}' in '{word}': {usual_count} of {len(places)} signs between "
                       f"two letters are '{usual}' (U+{ord(usual):04X})")
