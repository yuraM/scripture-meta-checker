"""Numbers compared with a base translation (Unit 3 > Numbers and spaces).

verse_numbers.txt keeps, per verse of an English base translation (Original numbers): the numbers of its text
(digits or words), the numbers of its notes, and the pairs "US measure = metric measure" of its notes. It holds
numbers only and is made by local_tools/make_verse_numbers.py.

- numbers-in-verse: a number written with digits in the text of a verse that the base translation does not have in
  that verse (text or notes): 265 years where others have 365, 590,300 for 59,300. Numbers written with words are not
  read (that needs the words of a language).
- us-measures: a note gives the number of a US measure where the base translation gives a US and a metric number
  ("about 25 tons or about 23 metric tons" -> the note says 25 'tons'). A US ton is 907 kg, so in a language where a
  ton is 1000 kg the number is wrong: always listed. Other measures (feet, pounds) are a choice of the project:
  listed only when the project gives the metric number in most other places.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterator
from functools import lru_cache
from pathlib import Path

from checker.footnotes import Note
from checker.model import WARNING, CheckContext, Finding
from checker.structure import PERIPHERAL_BOOKS

VERSE_NUMBERS = Path(__file__).with_name("verse_numbers.txt")
Key = tuple[str, int, int]
MIN_NUMBERS = 20  # numbers in digits needed to check numbers-in-verse (else the project writes numbers with words)
MIN_MEASURE_TYPO = 100  # in a verse with measures only numbers from 100 that differ by one digit are listed
MIN_PAIRS = 5  # notes that give a measure of the base translation, needed for us-measures
MIN_METRIC = 5  # a US number of feet, pounds … is listed when the project gives the metric number this often
MAX_US_SHARE = 0.2  # … and the US number in at most this share of the places
US_NAMES = {"t": ("US tons (907 kg)", "metric tons"), "p": ("pounds", "kilograms"), "o": ("ounces", "grams"),
            "f": ("feet", "metres"), "i": ("inches", "centimetres"), "m": ("miles", "kilometres"),
            "y": ("yards", "metres"), "g": ("gallons", "litres"), "q": ("quarts", "litres"),
            "n": ("pints", "litres"), "b": ("bushels", "litres")}
SPACES = " " + chr(0xA0) + chr(0x202F) + chr(0x2009)
FRACTION_MARKS = "⁄/"


class BaseNumbers:
    def __init__(self) -> None:
        self.text: dict[Key, Counter[float]] = {}  # a number twice when the verse has it twice
        self.notes: dict[Key, set[float]] = {}
        self.pairs: dict[Key, list[tuple[str, float, float]]] = {}


@lru_cache(maxsize=1)
def read_verse_numbers(path: Path = VERSE_NUMBERS) -> BaseNumbers:
    base = BaseNumbers()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        book, place, rest = line.split(" ", 2) if line.count(" ") >= 2 else (*line.split(" "), "")
        chapter, verse = (int(part) for part in place.split(":"))
        key = (book, chapter, verse)
        parts = [part.split() for part in rest.split("|")] + [[], []]
        base.text[key] = Counter(float(value) for value in parts[0])
        base.notes[key] = {float(value) for value in parts[1]}
        base.pairs[key] = [(item[0], float(us), float(metric))
                           for item in parts[2] for us, metric in [item[1:].split("=")]]
    return base


def _digits(text: str) -> str:
    """Any decimal digits (३, ፫ are not decimal) as 0-9; other characters kept."""
    return "".join(str(unicodedata.decimal(ch)) if ch.isdecimal() else ch for ch in text)


def numbers_of(text: str, separator: str, hindi_urdu: bool = False,
               chapter_verse: str = ":") -> list[tuple[int, int, float]]:
    """(start, end, value) of the numbers in digits. Groups joined by the thousands separator (or a space, a comma,
    a full stop before exactly 3 digits) are one number; "4,5" / "4.5" is a decimal number. Not counted: a number
    with a letter before it (H1234; a suffix after it is grammar: 1,260ን), a reference (3:16, both numbers), a fraction (1⁄2, 1/2)."""
    text = _digits(text)
    joiners = "".join(sorted(set(SPACES + ",." + separator)))
    found = []
    for match in re.finditer(r"\d+(?:[" + re.escape(joiners) + r"]\d+)*", text):
        start, end = match.start(), match.end()
        before = text[start - 1] if start else ""
        after = text[end] if end < len(text) else ""
        if (before.isalpha() or (before and before in FRACTION_MARKS)
                or (after and after in FRACTION_MARKS)
                or (before == chapter_verse and start >= 2 and text[start - 2].isdigit())
                or (after == chapter_verse and end + 1 < len(text) and text[end + 1].isdigit())):
            continue
        for offset, number, value in _read_number(match.group(), separator, hindi_urdu):
            found.append((start + offset, start + offset + len(number), value))
    return found


def _read_number(token: str, separator: str, hindi_urdu: bool) -> list[tuple[int, str, float]]:
    """A run of digit groups -> its numbers: "10 000" and "1,44,000" are one number, "4,5" a decimal number,
    "12, 15" two numbers."""
    groups = [(m.start(), m.group()) for m in re.finditer(r"\d+", token)]
    joints = [token[a[0] + len(a[1]):b[0]] for a, b in zip(groups, groups[1:])]
    if len(groups) == 1:
        return [(0, token, float(token))]
    lengths = [len(g) for _, g in groups[1:]]
    thousands = all(n == 3 for n in lengths) or (hindi_urdu and lengths[-1] == 3 and all(n == 2 for n in lengths[:-1]))
    if thousands and len(set(joints)) == 1 and (joints[0] == separator or joints[0] in SPACES + ",."):
        return [(0, token, float("".join(g for _, g in groups)))]
    if len(groups) == 2 and joints[0] in ",." and joints[0] != separator:
        return [(0, token, round(float(f"{groups[0][1]}.{groups[1][1]}"), 3))]
    return [(start, digits, float(digits)) for start, digits in groups]


def _one_digit_off(a: float, b: float) -> bool:
    """The digits of a and b differ by one digit added, left out or changed (59300 / 590300, 54400 / 54000)."""
    x, y = f"{a:g}", f"{b:g}"
    if abs(len(x) - len(y)) > 1 or x == y:
        return False
    if len(x) > len(y):
        x, y = y, x
    i = 0
    while i < len(x) and x[i] == y[i]:
        i += 1
    return x[i + (len(x) == len(y)):] == y[i + 1:]


def _show(value: float) -> str:
    return f"{value:,g}" if value < 1e6 else f"{value:,.0f}"


def check_numbers_in_verse(verse_texts: dict[Key, str], ranges: set, to_original: Callable | None,
                        ctx: CheckContext) -> Iterator[Finding]:
    if to_original is None:
        ctx.skipped["numbers-in-verse"] = (f"Not checked: the versification of the project "
                                        f"({ctx.settings.versification}) is not a standard one.")
        return
    base = read_verse_numbers()
    settings = ctx.settings
    shared: dict[tuple[str, int, str], list[Key]] = {}  # verses of one range (\v 6-7) share their text
    for key in ranges:
        shared.setdefault((key[0], key[1], verse_texts.get(key, "")), []).append(key)
    found_numbers = {}
    for key, text in verse_texts.items():
        if key[0] in PERIPHERAL_BOOKS:
            continue
        numbers = numbers_of(text, settings.number_thousands_separator, settings.hindi_urdu_grouping,
                             settings.chapter_verse_separator)
        if numbers:
            found_numbers[key] = numbers
    total = sum(len(numbers) for numbers in found_numbers.values())
    if total < MIN_NUMBERS:
        ctx.skipped["numbers-in-verse"] = (f"Not checked: the text has only {total} numbers in digits "
                                        "(numbers written with words are not read).")
        return

    def base_values(key: Key) -> Counter[float]:
        original = to_original(key)
        return base.text.get(original, Counter()) + Counter(base.notes.get(original, ()))

    for key in sorted(found_numbers, key=lambda k: (k[0], k[1], k[2])):
        keys = shared.get((key[0], key[1], verse_texts[key]), [key]) if key in ranges else [key]
        if key in ranges and key != min(keys):
            continue
        originals = [to_original(k) for k in keys]
        if not any(o in base.text or o in base.notes for o in originals):
            continue  # the base translation has no number here
        allowed = set().union(*(base_values(k) for k in keys))
        # The verse next to it in the base translation has the number more often than the project's verse next to
        # it: the verses are divided another way (NEH 7:67-68, where the base translation has 245 twice).
        for step in (-1, 1):
            near = (key[0], key[1], (min(keys) if step < 0 else max(keys))[2] + step)
            allowed |= set(base_values(near) - Counter(value for _, _, value in found_numbers.get(near, ())))
        # Its notes give measures: the project may give its own measure (litres, kilograms) in the text. Then only
        # a number that differs by one digit from a number of the base text is listed (2,500 for 25,000).
        measures = any(base.notes.get(o) for o in originals)
        expected = sorted(set().union(*(base.text.get(o, Counter()) for o in originals)))
        text = verse_texts[key]
        for start, end, value in found_numbers[key]:
            if value in allowed or (measures and not (value >= MIN_MEASURE_TYPO and any(
                    _one_digit_off(value, other) for other in expected))):
                continue
            number = text[start:end]
            others = ", ".join(_show(v) for v in expected if v >= 2) or "no such number"
            yield Finding(key[0], f"{key[1]}:{key[2]}", WARNING, "numbers-in-verse", number,
                          f"'{number}': other translations have {others} in this verse. Is the number right?",
                          " ".join(text[max(start - 50, 0):end + 50].split()))


def check_us_measures(notes: list[Note], to_original: Callable | None, ctx: CheckContext) -> Iterator[Finding]:
    if to_original is None:
        ctx.skipped["us-measures"] = (f"Not checked: the versification of the project "
                                      f"({ctx.settings.versification}) is not a standard one.")
        return
    base = read_verse_numbers()
    settings = ctx.settings
    note_values: dict[Key, set[float]] = {}
    note_of: dict[tuple[Key, float], Note] = {}
    for note in notes:
        chapter, _, verse = note.ref.partition(":")
        if note.book in PERIPHERAL_BOOKS or not chapter.isdigit() or not verse.isdigit():
            continue
        key = (note.book, int(chapter), int(verse))
        text = " ".join(part for marker, part in note.parts if marker not in ("fr", "xt", "fv", "xo"))
        for _, _, value in numbers_of(text, settings.number_thousands_separator, settings.hindi_urdu_grouping,
                                      settings.chapter_verse_separator):
            note_values.setdefault(key, set()).add(value)
            note_of.setdefault((key, value), note)
    us_places: dict[str, list[tuple[Key, float, float]]] = {}
    metric_count: Counter[str] = Counter()
    for key, values in note_values.items():
        for cls, us, metric in base.pairs.get(to_original(key), ()):
            if us in values and metric not in values:
                us_places.setdefault(cls, []).append((key, us, metric))
            elif metric in values and us not in values:
                metric_count[cls] += 1
    if sum(metric_count.values()) + sum(len(places) for places in us_places.values()) < MIN_PAIRS:
        ctx.skipped["us-measures"] = ("Not checked: the notes do not give the measures of the base translation "
                                      "(tons, feet, pounds …) in numbers.")
        return
    for cls, places in sorted(us_places.items()):
        if cls != "t" and (metric_count[cls] < MIN_METRIC or len(places) > MAX_US_SHARE * (len(places) + metric_count[cls])):
            continue  # US measures are the project's choice
        us_name, metric_name = US_NAMES[cls]
        for key, us, metric in places:
            note = note_of[(key, us)]
            yield Finding(key[0], f"{key[1]}:{key[2]}", WARNING, "us-measures", _show(us),
                          f"the note has '{_show(us)}', the number in {us_name}; in {metric_name} it is "
                          f"{_show(metric)}" + ("" if cls == "t" else
                                                f" (the project gives {metric_name} in {metric_count[cls]} other notes)"),
                          " ".join(note.raw.split())[:150])


NOTE_PAIR_PARTS = (100, 1000, 12, 16)  # "1 metre 80 cm" = 1.8, "2 kg 300 g" = 2.3, "7 feet 6 inches" = 7.5


def _same_number(value: float, allowed: set[float]) -> bool:
    """The same number, also written in another unit (3,400 kg = 3.4 t, 0.45 m = 45 cm)."""
    return any(round(value * 10 ** power, 6) in allowed for power in range(-3, 4))


def check_numbers_in_notes(notes: list[Note], verse_texts: dict[Key, str], verses: dict[str, dict[int, set[int]]],
                       to_original: Callable | None, ctx: CheckContext) -> Iterator[Finding]:
    """Numbers of a note that the notes and the text of the base translation do not have in that verse. Only verses
    where both the project and the base translation have a note with numbers are compared."""
    if to_original is None:
        ctx.skipped["numbers-in-notes"] = (f"Not checked: the versification of the project "
                                       f"({ctx.settings.versification}) is not a standard one.")
        return
    base = read_verse_numbers()
    settings = ctx.settings
    compared = 0
    findings = []
    for note in notes:
        chapter, _, verse = note.ref.partition(":")
        if note.book in PERIPHERAL_BOOKS or not chapter.isdigit() or not verse.isdigit():
            continue
        key = (note.book, int(chapter), int(verse))
        original = to_original(key)
        if not base.notes.get(original):
            continue
        text = " ".join(part for marker, part in note.parts if marker not in ("fr", "xt", "fv", "xo"))
        numbers = numbers_of(text, settings.number_thousands_separator, settings.hindi_urdu_grouping,
                             settings.chapter_verse_separator)
        if not numbers:
            continue
        compared += 1
        allowed = set(base.text.get(original, ())) | base.notes[original]
        for step in (-1, 1):
            near = (original[0], original[1], original[2] + step)
            allowed |= set(base.text.get(near, ())) | base.notes.get(near, set())
        allowed |= {value for _, _, value in numbers_of(verse_texts.get(key, ""), settings.number_thousands_separator,
                                                        settings.hindi_urdu_grouping, settings.chapter_verse_separator)}
        chapter_verses = verses.get(key[0], {}).get(key[1], set())
        expected = ", ".join(_show(v) for v in sorted(base.notes[original]))
        used = set()
        for index, (start, end, value) in enumerate(numbers):
            if index in used:
                continue
            shown_end = end
            # "1 metre 8 cm" where the base note has 1.8: one number written in two parts (here 1.08: listed).
            if index + 1 < len(numbers) and value == int(value):
                next_start, next_end, part = numbers[index + 1]
                gap = text[end:next_start]
                if (part < 100 and len(gap) < 20 and not any(ch.isdigit() or ch in ",;:()" for ch in gap)
                        and any(v != int(v) and int(v) == value for v in allowed)):
                    used.add(index + 1)
                    if (any(_same_number(value + part / size, allowed) for size in NOTE_PAIR_PARTS)
                            or (value in allowed and part in allowed)):  # "1 quart or about 1 liter"
                        continue
                    shown_end = next_end
                    value = None
            if value is not None:
                if value == int(value) and (value < 10 or int(value) in chapter_verses):
                    continue  # a small number, or a verse of this chapter ("also in verse 21")
                if _same_number(value, allowed):
                    continue
            shown = text[start:shown_end]
            findings.append(Finding(key[0], f"{key[1]}:{key[2]}", WARNING, "numbers-in-notes", shown,
                                    f"the note has '{shown}': the notes of other translations have {expected} "
                                    "in this verse. Is the number right?", " ".join(note.raw.split())[:150]))
    if compared < MIN_PAIRS:
        ctx.skipped["numbers-in-notes"] = ("Not checked: the notes of the project and of the base translation have "
                                       f"numbers in the same verse only {compared} times.")
        return
    yield from findings
