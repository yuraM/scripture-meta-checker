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
from collections.abc import Callable, Iterator

from checker.model import WARNING, Analysis, CheckContext, Finding
from checker.structure import PERIPHERAL_BOOKS
from checker.tokens import LETTER
from checker.usfm import Segment

MIN_USUAL = 20  # the usual form is used at least this often
MIN_SHARE = 0.9  # and in at least this part of the places
QUOTE_WORDS_RE = re.compile(rf"{LETTER}+(?:['’ʼ\-]{LETTER}+)*")  # words, also with an apostrophe
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


UNTRANSLATED_MIN_LETTERS = 20  # a verse with fewer letters says too little about its language
OTHER_SCRIPT_SHARE = 0.5  # this part of the letters in another script than the project's: another language
UNTRANSLATED_MIN_WORDS = 5  # small-letter words needed for the second sign
ONLY_HERE_SHARE = 0.7  # this part of them occurs nowhere else in the project


def _script(ch: str) -> str:
    return unicodedata.name(ch, "?").split()[0]


def check_untranslated(verse_texts: dict[tuple[str, int, int], str], word_counts: Counter,
                       ctx: CheckContext) -> Iterator[Finding]:
    """A verse that looks untranslated (left in the source or another language): most of its letters are in another
    script than the project, or nearly all its small-letter words occur nowhere else in the project (an English
    verse in an Indonesian text). Names are capitalized, so lists of names do not count; a list of rare words
    (animals, vices) may. Front/back matter is not checked: its tables often have English names."""
    texts = {key: text for key, text in verse_texts.items() if key[0] not in PERIPHERAL_BOOKS}
    letters = Counter(_script(ch) for text in texts.values() for ch in text if ch.isalpha())
    if not letters:
        return
    main = letters.most_common(1)[0][0]
    for (book, chapter, verse), text in sorted(texts.items(), key=lambda item: item[0][1:]):
        verse_letters = [ch for ch in text if ch.isalpha()]
        other = sum(_script(ch) != main for ch in verse_letters)
        words = [word for word in QUOTE_WORDS_RE.findall(text) if word[0].islower()]
        here = Counter(words)
        only_here = [word for word in words if word_counts[word] <= here[word]]
        if len(verse_letters) >= UNTRANSLATED_MIN_LETTERS and other >= len(verse_letters) * OTHER_SCRIPT_SHARE:
            why = f"{other} of its {len(verse_letters)} letters are not {main.title()}"
        elif len(words) >= UNTRANSLATED_MIN_WORDS and len(only_here) >= len(words) * ONLY_HERE_SHARE:
            why = f"{len(only_here)} of its {len(words)} words occur nowhere else in the project"
        else:
            continue
        yield Finding(book, f"{chapter}:{verse}", WARNING, "untranslated-verses", f"{chapter}:{verse}",
                      f"the verse may be untranslated or in another language: {why}", text[:2 * 50])


# --- dashes, ellipses, headings, note callers: the rare way of the project ---

SPACED_DASH_RE = re.compile(r"(?<=\s)([‐-―−-])(?=\s)")
ELLIPSIS_RE = re.compile(r"…|(?<!\.)\.\.\.(?!\.)|(?<!\.)\. \. \.(?! \.)")
HEADING_STYLE_RE = re.compile(r"(s\d?|ms\d?)$")
MIN_HEADING_WORDS = 2  # words after the first, written small elsewhere, needed to see the case of a heading
NOTE_CALLER_RE = re.compile(re.escape(chr(92)) + r"(f|fe|ef|x|ex)\s+(\S+)")


def _rare(places: list, form_of: Callable, check: str, what: str, message: Callable) -> Iterator[Finding]:
    """Findings for the places whose form is not the usual one (used in >=90% of >=20 places)."""
    counts = Counter(form_of(place) for place in places)
    if len(counts) < 2:
        return
    usual, usual_count = counts.most_common(1)[0]
    if usual_count < MIN_USUAL or usual_count < len(places) * MIN_SHARE:
        return
    for place in places:
        form = form_of(place)
        if form != usual:
            yield message(place, form, usual, usual_count, len(places))


def _most(places: list) -> str:
    return Counter(place[1].group(1) for place in places).most_common(1)[0][0] if places else ""


def _sign_name(sign: str) -> str:
    return f"'{sign}' ({unicodedata.name(sign, 'U+%04X' % ord(sign)).lower()})"


def check_dashes(segments: list[Segment], ctx: CheckContext) -> Iterator[Finding]:
    """A dash between two spaces that is not the dash the project nearly always uses there (' - ' among ' – ')."""
    texts = [segment for segment in segments if segment.book not in PERIPHERAL_BOOKS]
    places = [(segment, match) for segment in texts for match in SPACED_DASH_RE.finditer(segment.text)]
    # A dash used often elsewhere (at the start of a line of dialogue) has another role: not a rare form.
    everywhere = Counter(ch for segment in texts for ch in segment.text if unicodedata.category(ch) == "Pd")
    places = [place for place in places
              if everywhere[place[1].group(1)] < MIN_USUAL or place[1].group(1) == _most(places)]

    def message(place, form, usual, usual_count, total):
        segment, match = place
        return _finding(segment, match.start(), 1, "dashes", form,
                        f"change {_sign_name(form)} to {_sign_name(usual)}: {usual_count} of {total} dashes between "
                        f"spaces are '{usual}'")
    yield from _rare(places, lambda place: place[1].group(1), "dashes", "dash", message)


def check_ellipses(segments: list[Segment], ctx: CheckContext) -> Iterator[Finding]:
    """An ellipsis written another way than the project nearly always writes it ('...' among '…')."""
    places = [(segment, match) for segment in segments if segment.book not in PERIPHERAL_BOOKS
              for match in ELLIPSIS_RE.finditer(segment.text)]

    def message(place, form, usual, usual_count, total):
        segment, match = place
        return _finding(segment, match.start(), len(form), "ellipses", form,
                        f"change '{form}' to '{usual}': {usual_count} of {total} ellipses are written '{usual}'")
    yield from _rare(places, lambda place: place[1].group(), "ellipses", "ellipsis", message)


def check_heading_case(flow: list[Segment], case_refs: dict, ctx: CheckContext) -> Iterator[Finding]:
    """Headings of one style written with a capital on each word (Title Case) or only on the first (Sentence case):
    the rare way is listed. Only words that are written small everywhere else count, so names do not."""
    by_style: dict[str, list] = {}
    for segment in flow:
        if not HEADING_STYLE_RE.match(segment.style) or segment.book in PERIPHERAL_BOOKS:
            continue
        # Words after ":" or a dash start a new part ("Plague six: Boils"), so only the part before counts.
        words = QUOTE_WORDS_RE.findall(re.split(r"[:\u2010-\u2015]", segment.text)[0])[1:]
        small = [word for word in words if word[0].isalpha() and not word.isupper()
                 and not case_refs.get(word.lower(), ([1], []))[0] and len(case_refs.get(word.lower(), ([], []))[1]) >= 3]
        if len(small) >= MIN_HEADING_WORDS:
            capitals = [word for word in small if word[0].isupper()]
            title = len(capitals) >= 2 and len(capitals) * 2 >= len(small)
            by_style.setdefault(segment.style, []).append((segment, title, small, capitals))
    for style, places in by_style.items():
        def message(place, form, usual, usual_count, total):
            segment, title, small, capitals = place
            if title:
                how, example = "a capital on each word", f"write '{capitals[0].lower()}'"
            else:
                how, example = "a capital only on the first word", f"write '{small[0].capitalize()}'"
            return _finding(segment, 0, 1, "heading-case", segment.text.strip()[:60],
                            f"this heading \\{style} has {how}, but {usual_count} of {total} headings \\{style} are "
                            f"written the other way: {example}")
        yield from _rare(places, lambda place: place[1], "heading-case", "heading", message)


def check_note_callers(sources: list[tuple[str, str]], ctx: CheckContext) -> Iterator[Finding]:
    """The caller of a note (\\f + …, \\x - …) that is not the one the project nearly always uses for that kind of note."""
    from checker.verses import RawRefs
    by_marker: dict[str, list] = {}
    refs: dict[str, RawRefs] = {}
    for book, content in sources:
        for match in NOTE_CALLER_RE.finditer(content):
            caller = match.group(2)
            form = caller if caller in ("+", "-") else "a letter or number"
            by_marker.setdefault(match.group(1), []).append((book, content, match, form))
    for marker, places in by_marker.items():
        def message(place, form, usual, usual_count, total):
            book, content, match, _ = place
            chapter, verse = refs.setdefault(book, RawRefs(content)).at(match.start())
            shown = "+ (numbered by the program)" if usual == "+" else ("- (no caller)" if usual == "-" else usual)
            return Finding(book, f"{chapter}:{verse}", WARNING, "note-callers", f"\\{marker} {match.group(2)}",
                           f"the note \\{marker} has the caller '{match.group(2)}', but {usual_count} of {total} notes "
                           f"\\{marker} use {shown}", " ".join(content[match.start():match.start() + 80].split()))
        yield from _rare(places, lambda place: place[3], "note-callers", "caller", message)
