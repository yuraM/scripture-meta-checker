"""Checks of the text of verses and of what is linked to it (Unit 2): nothing is changed, the reports only say where.

- repeated-text: a verse with the same words as the verse before it (copied twice), or a group of 3+ words written
  twice in a row ("he went to the city he went to the city"). Verse ranges (\\v 6-7) share one text and are skipped.
  The same sentence twice inside a verse is not listed: in the Bible that is nearly always on purpose (ISA 8:9).
- verse-lengths: a verse 3 times shorter or longer than usual, compared with an English base translation
  (verse_lengths.txt: letters per verse, numbers only). "Usual" is the project's own median ratio, so the language
  does not matter. Finds half-translated verses, verses merged or split, verses numbered another way.
- glossary-words: a word marked \\w (glossary word) with no entry \\k in the glossary book GLO.
- figures: a picture \\fig without a file name, for another verse than the one it stands in, or (when the project
  has a figures folder) whose file is not there.
"""
from __future__ import annotations

import bisect
import re
import statistics
from collections.abc import Callable, Iterator
from pathlib import Path

from checker.model import WARNING, CheckContext, Finding
from checker.structure import PERIPHERAL_BOOKS
from checker.tokens import LETTER

WORD_RE = re.compile(rf"{LETTER}+")
MIN_SAME_WORDS = 5  # a repeated verse has at least this many words
MIN_PHRASE = 3  # words of a phrase written twice in a row
TWICE_RE = re.compile(rf"(?<!{LETTER})((?:{LETTER}+\s+){{{MIN_PHRASE - 1},}}{LETTER}+)\s+\1(?!{LETTER})",
                      re.IGNORECASE)
VERSE_LENGTHS = Path(__file__).with_name("verse_lengths.txt")
MIN_BASE_LETTERS = 40  # shorter base verses say too little
LENGTH_FACTOR = 3  # 3 times shorter or longer than the usual ratio
MIN_COMMON_VERSES = 200  # verses needed to know the usual ratio of a project
B = re.escape(chr(92))
CHAPTER_RE = re.compile(B + r"c\s+(\d+)")
VERSE_RE = re.compile(B + r"v\s+(\S+)")
GLOSSARY_WORD_RE = re.compile(B + r"\+?w\s+(.*?)" + B + r"\+?w\*", re.S)
KEYWORD_RE = re.compile(B + r"k\s+(.*?)" + B + r"k\*", re.S)
FIGURE_RE = re.compile(B + r"fig\s*(.*?)" + B + r"fig\*", re.S)
ATTRIBUTE_RE = re.compile(r'(\w[\w-]*)\s*=\s*"([^"]*)"')
REF_NUMBERS_RE = re.compile(r"(\d+)\D(\d+)\s*$")


def _verse_key(key: tuple[str, int, int]) -> str:
    return f"{key[1]}:{key[2]}"


def check_repeated_text(verse_texts: dict[tuple[str, int, int], str], ranges: set) -> Iterator[Finding]:
    keys = sorted(verse_texts)
    previous: tuple[tuple[str, int, int], list[str]] | None = None
    for key in keys:
        text = verse_texts[key]
        words = [word.casefold() for word in WORD_RE.findall(text)]
        if key[0] in PERIPHERAL_BOOKS:
            previous = None
            continue
        if (previous and previous[0][:2] == key[:2] and previous[0][2] == key[2] - 1 and key not in ranges
                and previous[0] not in ranges and len(words) >= MIN_SAME_WORDS and words == previous[1]):
            yield Finding(key[0], _verse_key(key), WARNING, "repeated-text", _verse_key(key),
                          f"verse {key[2]} has the same words as verse {key[2] - 1}: copied twice?", text)
        previous = (key, words)
        # Only a copy with nothing but spaces between: "Answer me, answer me" and "My father! My father!" repeat on
        # purpose and have a comma or a mark between the two.
        if match := TWICE_RE.search(text):
            phrase = " ".join(match.group(1).split())
            yield Finding(key[0], _verse_key(key), WARNING, "repeated-text", phrase,
                          f"'{phrase}' is written twice in a row", text)


def read_verse_lengths(path: Path = VERSE_LENGTHS) -> dict[tuple[str, int, int], int]:
    lengths = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        book, place, counts = line.split(" ", 2)
        chapter, first = (int(part) for part in place.split(":"))
        for verse, count in enumerate(counts.split(","), start=first):
            if int(count):
                lengths[(book, chapter, verse)] = int(count)
    return lengths


def check_verse_lengths(verse_texts: dict[tuple[str, int, int], str], ranges: set,
                        to_original: Callable | None, ctx: CheckContext) -> Iterator[Finding]:
    if to_original is None:
        ctx.skipped["verse-lengths"] = (f"Not checked: the versification of the project "
                                        f"({ctx.settings.versification}) is not a standard one.")
        return
    base = read_verse_lengths()
    ratios = {}
    for key, text in verse_texts.items():
        if key in ranges or key[0] in PERIPHERAL_BOOKS:
            continue
        letters = sum(ch.isalpha() for ch in text)
        other = base.get(to_original(key), 0)
        if letters and other >= MIN_BASE_LETTERS:
            ratios[key] = (letters / other, letters, other)
    if len(ratios) < MIN_COMMON_VERSES:
        ctx.skipped["verse-lengths"] = (f"Not checked: only {len(ratios)} verses can be compared; "
                                        f"{MIN_COMMON_VERSES} are needed to know the usual length.")
        return
    usual = statistics.median(ratio for ratio, _, _ in ratios.values())
    for key in sorted(ratios):
        ratio, letters, other = ratios[key]
        expected = round(other * usual)
        if ratio < usual / LENGTH_FACTOR:
            how = "much shorter"
        elif ratio > usual * LENGTH_FACTOR:
            how = "much longer"
        else:
            continue
        yield Finding(key[0], _verse_key(key), WARNING, "verse-lengths", how,
                      f"the verse is {how} than usual: {letters} letters, about {expected} expected from other "
                      "translations. Is a part missing or added, or is it numbered another way?",
                      verse_texts[key][:100])


class RawRefs:
    """chapter:verse of an offset in a raw USFM file."""

    def __init__(self, content: str) -> None:
        self.chapters = [(m.start(), int(m.group(1))) for m in CHAPTER_RE.finditer(content)]
        self.verses = [(m.start(), m.group(1)) for m in VERSE_RE.finditer(content)]

    def at(self, offset: int) -> tuple[int, str]:
        index = bisect.bisect_right(self.chapters, (offset, 10 ** 9)) - 1
        chapter = self.chapters[index][1] if index >= 0 else 0
        chapter_start = self.chapters[index][0] if index >= 0 else -1
        index = bisect.bisect_right(self.verses, (offset, "￿")) - 1
        verse = self.verses[index][1] if index >= 0 and self.verses[index][0] > chapter_start else "0"
        return chapter, verse


def _context(content: str, start: int, end: int) -> str:
    return " ".join(content[max(start - 40, 0):end + 40].split())


def _same_word(word: str, keyword: str) -> bool:
    """Equal, or the same stem (another ending): the glossary has the base form, the text an inflected one."""
    if word == keyword:
        return True
    stem = max(3, min(len(word), len(keyword)) - 3)
    return len(word) > 3 and len(keyword) > 3 and word[:stem] == keyword[:stem]


def check_glossary_words(sources: list[tuple[str, str]], ctx: CheckContext) -> Iterator[Finding]:
    keywords = {" ".join(m.group(1).split()).casefold()
                for book, content in sources if book == "GLO" for m in KEYWORD_RE.finditer(content)}
    marked = [(book, content, m) for book, content in sources for m in GLOSSARY_WORD_RE.finditer(content)]
    if not marked:
        ctx.skipped["glossary-words"] = "Not checked: the text has no glossary words (\\w … \\w*)."
        return
    if not keywords:
        ctx.skipped["glossary-words"] = (f"Not checked: the text marks {len(marked)} glossary words (\\w), but the "
                                         "project has no glossary book GLO with entries (\\k), or it was not checked.")
        return
    refs: dict[str, RawRefs] = {}
    for book, content, match in marked:
        word, _, attributes = match.group(1).partition("|")
        word = " ".join(word.split())
        lemma = dict(ATTRIBUTE_RE.findall(attributes)).get("lemma", "" if "=" in attributes else attributes.strip())
        forms = {form.casefold() for form in (word, lemma) if form}
        if any(_same_word(form, keyword) for form in forms for keyword in keywords):
            continue
        chapter, verse = refs.setdefault(book, RawRefs(content)).at(match.start())
        shown = lemma or word
        yield Finding(book, f"{chapter}:{verse}", WARNING, "glossary-words", shown,
                      f"the glossary word '{shown}' (\\w) has no entry (\\k) in the glossary book GLO",
                      _context(content, match.start(), match.end()))


def _figure_parts(inner: str) -> tuple[str, str]:
    """(file, reference) of \\fig: USFM 3 attributes (src="…" ref="…") or the USFM 2 fields
    DESC|FILE|SIZE|LOC|COPY|CAP|REF."""
    if "=" in inner.partition("|")[2]:
        attributes = dict(ATTRIBUTE_RE.findall(inner.partition("|")[2]))
        return attributes.get("src", "").strip(), attributes.get("ref", "").strip()
    fields = inner.split("|")
    return (fields[1].strip() if len(fields) > 1 else ""), (fields[6].strip() if len(fields) > 6 else "")


def check_figures(sources: list[tuple[str, str]], project: Path | None, ctx: CheckContext) -> Iterator[Finding]:
    figures = [(book, content, m) for book, content in sources for m in FIGURE_RE.finditer(content)]
    if not figures:
        ctx.skipped["figures"] = "Not checked: the text has no pictures (\\fig)."
        return
    folder = next((path for name in ("figures", "Figures", "local/figures")
                   if project and (path := project / name).is_dir()), None)
    files = {path.name.casefold() for path in folder.iterdir()} if folder else set()
    refs: dict[str, RawRefs] = {}
    for book, content, match in figures:
        chapter, verse = refs.setdefault(book, RawRefs(content)).at(match.start())
        place = f"{chapter}:{verse}"
        context = _context(content, match.start(), match.end())
        file, reference = _figure_parts(match.group(1))
        if not file:
            yield Finding(book, place, WARNING, "figures", "no file", "the picture \\fig has no file name", context)
        elif folder and Path(file).name.casefold() not in files:
            yield Finding(book, place, WARNING, "figures", file,
                          f"the picture file '{file}' is not in the folder {folder.name} of the project", context)
        numbers = REF_NUMBERS_RE.search(reference)
        first = re.match(r"\d+", verse)
        if numbers and first and (int(numbers.group(1)) != chapter
                                  or abs(int(numbers.group(2)) - int(first.group())) > 2):
            yield Finding(book, place, WARNING, "figures", reference,
                          f"the picture is for {reference}, but it stands in {place}", context)
