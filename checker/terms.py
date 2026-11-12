"""Biblical terms: the project's terms list (verses of each term) and TermRenderings.xml (its renderings).

Paratext files (Biblical Terms window):
- the terms list named by Settings.xml BiblicalTermsListSetting ("Project:<name>:ProjectBiblicalTerms.xml"); only a
  list inside the project folder is used. <Term Id> with <References><Verse>BBBCCCVVVnn</Verse>, in the
  versification of the project.
- TermRenderings.xml: <TermRendering Id Guess> with <Renderings>a||b</Renderings>, <Denials><Denial>BBBCCCVVV</Denial>
  (verses where the term is not rendered on purpose).

A rendering is the start of a word ("Варавв" = Варавва, Вараввою); * stands for any letters, ** for any words,
(text in brackets) is a comment. The words of a phrase may be separated by anything that is not a letter.

Checks:
- terms: clear cases only. A rendering missing in a verse is reported when the term is rendered in almost all its
  other verses (missing in at most MAX_MISSING verses and at most MAX_MISSING_SHARE of them). The rest is counted
  and explained in the report note, not listed. Renderings that match no word of the text are reported too.
- term-lists: the lists themselves: denials where the rendering is there now, denials of verses that are not
  verses of the term, renderings guessed by Paratext and never checked by a person.
"""
from __future__ import annotations

import bisect
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from checker.books import BOOK_CODES
from checker.model import WARNING, CheckContext, Finding
from checker.versification import CUSTOM_VRS, original_to_project

if TYPE_CHECKING:
    from checker.checks import UsageCounter

RENDERINGS_FILE = "TermRenderings.xml"
PLACE = "Biblical Terms"  # Paratext: Tools > Biblical Terms
MAX_MISSING = 2           # a term missing in more verses is a word translated in many ways, not a clear case
MAX_MISSING_SHARE = 0.05  # ... or missing in more than 5% of its verses
MAX_LISTED_GUESSES = 100  # more guessed renderings are reported in one line
CONTEXT_CHARS = 60


@dataclass
class Term:
    id: str
    gloss: str
    verses: list[tuple[str, int, int]]


@dataclass
class TermRendering:
    renderings: list[str]
    guess: bool
    denials: set[tuple[str, int, int]] = field(default_factory=set)


@dataclass
class TermData:
    list_name: str
    terms: list[Term]
    renderings: dict[str, TermRendering]
    note: str = ""  # which list was used (shown in the reports)


def _verse(number: str) -> tuple[str, int, int] | None:
    """"04400702200" / "43011002" (BBBCCCVVV + optional word number) -> ("ACT", 7, 22)."""
    digits = number.strip()
    if not digits.isdigit():
        return None
    value = int(digits[:9]) if len(digits) > 9 else int(digits)
    book = value // 1_000_000
    if not 1 <= book <= len(BOOK_CODES):
        return None
    return BOOK_CODES[book - 1], value // 1000 % 1000, value % 1000


def list_file_name(setting: str) -> str:
    """"Project:ukrNPUv1:ProjectBiblicalTerms.xml" -> "ProjectBiblicalTerms.xml"; "Major::BiblicalTerms.xml" too."""
    return setting.rsplit(":", 1)[-1].strip()


PROJECT_LIST = "ProjectBiblicalTerms.xml"
# Settings.xml <Versification> number -> the name a terms list writes ("English-3e02…").
VERSIFICATIONS = {"1": "Original", "2": "Septuagint", "3": "Vulgate", "4": "English",
                  "5": "RussianProtestant", "6": "RussianOrthodox"}


def paratext_program_folder() -> Path | None:
    """The Paratext program folder (it has Terms/Lists/BiblicalTerms.xml): from the registry, else the usual place."""
    try:
        import winreg

        for key_path in (r"SOFTWARE\WOW6432Node\Paratext\8", r"SOFTWARE\Paratext\8"):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                    folder = Path(winreg.QueryValueEx(key, "Paratext9_Full_Release_AppPath")[0])
                    if folder.is_dir():
                        return folder
            except OSError:
                continue
    except ImportError:  # not Windows
        pass
    folder = Path("C:/Program Files/Paratext 9")
    return folder if folder.is_dir() else None


def _find_list(project: Path, list_setting: str) -> tuple[Path | None, str]:
    """(path of the terms list, note). The list chosen in Paratext: in the project folder, or (Major, All) in the
    Paratext program folder; else the project list ProjectBiblicalTerms.xml if the folder has one."""
    chosen = list_file_name(list_setting) if list_setting else ""
    if chosen and (project / chosen).is_file():
        return project / chosen, ""
    program = paratext_program_folder()
    if chosen and not list_setting.startswith("Project:") and program:
        path = program / "Terms" / "Lists" / chosen
        if path.is_file():
            return path, "from the Paratext program folder"
    if (project / PROJECT_LIST).is_file():
        note = (f"Paratext uses the list {list_setting} for this project; it was not found, so only "
                f"{PROJECT_LIST} of the project folder is checked." if chosen and chosen != PROJECT_LIST else "")
        return project / PROJECT_LIST, note
    return None, ""


def load_terms(project: Path, list_setting: str, versification: str = "") -> tuple[TermData | None, str]:
    """(the terms list and renderings, a note) or (None, why not).

    Verse numbers of the list are changed to the versification of the project: the lists of the Paratext program
    folder count verses as Original (org.vrs); an English project is reached through eng.vrs + custom.vrs.
    """
    renderings_path = project / RENDERINGS_FILE
    if not renderings_path.is_file():
        return None, f"the project folder has no {RENDERINGS_FILE}"
    list_path, where = _find_list(project, list_setting)
    if list_path is None:
        return None, f"the terms list {list_setting or PROJECT_LIST} was not found"
    root = ET.parse(list_path).getroot()
    # Lists of the program folder have no <Versification>: they count verses as Original.
    list_versification = (root.findtext("Versification") or "Original").split("-", 1)[0]
    project_versification = VERSIFICATIONS.get(versification.strip(), "English")
    if list_versification == project_versification:
        mapping: dict = {}
    elif list_versification == "Original" and project_versification == "English":
        mapping = original_to_project(project)
    else:
        return None, (f"{list_path.name} counts verses as {list_versification}, the project as "
                      f"{project_versification}; there is no file to change one into the other")
    terms = []
    for term in root.iter("Term"):
        verses = [v for v in (_verse(e.text or "") for e in term.iter("Verse")) if v]
        verses = list(dict.fromkeys(mapping.get(v, v) for v in verses))
        terms.append(Term(term.get("Id", ""), (term.findtext("Gloss") or "").strip(), verses))
    note = f"Terms list: {list_path.name} ({len(terms)} terms)"
    note += f", {where}." if where.startswith("from") else "."
    if mapping:
        note += " Its verse numbers (Original) were changed to the English numbers of the project (eng.vrs"
        note += " + custom.vrs)." if (project / CUSTOM_VRS).is_file() else ")."
    if where and not where.startswith("from"):
        note += " " + where
    renderings = {}
    for item in ET.parse(renderings_path).getroot().iter("TermRendering"):
        text = (item.findtext("Renderings") or "").strip()
        denials = {v for v in (_verse(e.text or "") for e in item.iter("Denial")) if v}
        renderings[item.get("Id", "")] = TermRendering(
            [unicodedata.normalize("NFC", r.strip()) for r in text.split("||") if r.strip()], item.get("Guess") == "true", denials)
    return TermData(list_path.name, terms, renderings, note), ""


def rendering_pattern(rendering: str) -> re.Pattern[str] | None:
    """Regex for a rendering in lowercase text; None if it is only a comment."""
    words = re.sub(r"\([^)]*\)", " ", rendering.lower()).split()
    parts = [r"(?:\w+\W+)*?" if word == "**" else re.escape(word).replace(r"\*", r"\w*")
             for word in words]
    if not any(part != r"(?:\w+\W+)*?" for part in parts):
        return None
    pattern = ""
    for index, part in enumerate(parts):
        if index and parts[index - 1] != r"(?:\w+\W+)*?":
            pattern += r"\w*\W+"
        pattern += part
    return re.compile(r"(?<!\w)" + pattern)


def _skipped(ctx: CheckContext, check: str) -> bool:
    if ctx.terms is None:
        ctx.skipped[check] = (f"Not checked: {ctx.terms_problem or 'no terms files'}. The checks need "
                              f"{RENDERINGS_FILE} and the terms list (the one chosen in Paratext, or {PROJECT_LIST}) "
                              f"in the project folder. Paratext: {PLACE}.")
        return True
    if ctx.terms.note:
        ctx.notes[check] = ctx.terms.note
    return False


def _quoted(renderings: list[str]) -> str:
    """'a' || 'b': each rendering in quotes, so the HTML report can copy each one."""
    return " || ".join(f"'{item}'" for item in renderings)


def _context(text: str) -> str:
    return text if len(text) <= CONTEXT_CHARS * 2 else text[:CONTEXT_CHARS * 2] + "…"


def _verse_texts(usage: UsageCounter) -> dict[tuple[str, int, int], str]:
    """Lowercase verse texts. Verse 1 also gets the title \\d of its chapter (verse 0): in the original text a
    psalm title is often part of verse 1 (PSA 90:1), and the versification files do not always move it."""
    texts = {key: text.lower() + " " for key, text in usage.verse_texts.items()}
    for (book, chapter, verse), text in list(texts.items()):
        if verse == 0 and (book, chapter, 1) in texts:
            texts[(book, chapter, 1)] = text + texts[(book, chapter, 1)]
    return texts


def check_terms(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    if _skipped(ctx, "terms"):
        return
    data: TermData = ctx.terms
    lower = _verse_texts(usage)
    hidden_terms = hidden_verses = guessed = 0
    for term in data.terms:
        rendering = data.renderings.get(term.id)
        if not rendering or not rendering.renderings:
            continue
        if rendering.guess:
            guessed += 1
            continue
        patterns = [p for p in map(rendering_pattern, rendering.renderings) if p]
        if not patterns:
            continue
        checked, missing = 0, []
        for verse in term.verses:
            if verse in rendering.denials or verse not in lower:
                continue
            checked += 1
            if not any(p.search(lower[verse]) for p in patterns):
                missing.append(verse)
        if not missing:
            continue
        if len(missing) > MAX_MISSING or len(missing) > checked * MAX_MISSING_SHARE:
            hidden_terms += 1
            hidden_verses += len(missing)
            continue
        gloss = f" ({term.gloss})" if term.gloss else ""
        for book, chapter, verse in missing:
            yield Finding(book, f"{chapter}:{verse}", WARNING, "terms", term.id,
                          f"the term '{term.id}'{gloss} is rendered in {checked - len(missing)} of its {checked} "
                          f"verses, but not here. Renderings: {_quoted(rendering.renderings)}",
                          _context(usage.verse_texts[(book, chapter, verse)]))
    ctx.notes["terms"] = (
        (data.note + " " if data.note else "") +
        f"Not listed (not clear): {hidden_verses} verses of {hidden_terms} terms whose rendering is missing in more "
        f"than {MAX_MISSING} verses or in more than {MAX_MISSING_SHARE:.0%} of their verses. These are mostly common "
        f"words that are translated in many ways (write, believe, forever); see them in Paratext {PLACE}. "
        f"Also not checked: verses marked OK without a rendering"
        + (f", {guessed} terms with a rendering guessed by Paratext (see term-lists)." if guessed else "."))
    yield from _unused_renderings(data, usage, lower)


def _unused_renderings(data: TermData, usage: UsageCounter, lower: dict) -> Iterator[Finding]:
    """Renderings that match no word of the text: a typo or an old rendering."""
    words = sorted({word.lower() for word in usage.words})
    for term in data.terms:
        rendering = data.renderings.get(term.id)
        if not rendering:
            continue
        for item in rendering.renderings:
            pattern = rendering_pattern(item)
            if not pattern:
                continue
            if " " in item.strip() or "**" in item:
                # Search only the verses that contain the longest plain part of the phrase.
                plain = max(re.split(r"[\s*]+", re.sub(r"\([^)]*\)", " ", item.lower())), key=len)
                found = any(plain in text and pattern.search(text) for text in lower.values())
            else:
                # Only words that start with the letters before the first * can match: a range of the sorted list.
                start = re.sub(r"\([^)]*\)", "", item).strip().lower().split("*", 1)[0]
                first = bisect.bisect_left(words, start)
                found = False
                for word in words[first:]:
                    if not word.startswith(start):
                        break
                    if pattern.match(word):
                        found = True
                        break
            if not found:
                yield Finding(PLACE, "(renderings)", WARNING, "terms", item,
                              f"the rendering '{item}' of the term '{term.id}' is not found anywhere in the text",
                              "")


def check_term_lists(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    if _skipped(ctx, "term-lists"):
        return
    data: TermData = ctx.terms
    verses_of = {term.id: set(term.verses) for term in data.terms}
    lower = _verse_texts(usage)
    # TermRenderings.xml also keeps terms of other lists; Paratext shows only the terms of the list in use.
    guessed = [(term_id, rendering) for term_id, rendering in data.renderings.items()
               if term_id in verses_of and rendering.guess and rendering.renderings]
    if len(guessed) > MAX_LISTED_GUESSES:
        examples = ", ".join(f"{term_id} '{rendering.renderings[0]}'" for term_id, rendering in guessed[:5])
        yield Finding(PLACE, "(guessed)", WARNING, "term-lists", "guessed",
                      f"{len(guessed)} renderings were guessed by Paratext and are not checked by a person (in "
                      f"Paratext {PLACE}, show the guessed renderings to check them), e.g. {examples}", "")
    else:
        for term_id, rendering in guessed:
            yield Finding(PLACE, "(guessed)", WARNING, "term-lists", term_id,
                          f"the rendering {_quoted(rendering.renderings)} of the term '{term_id}' was guessed by "
                          f"Paratext and is not checked by a person", "")
    for term_id, rendering in data.renderings.items():
        if term_id not in verses_of:
            continue
        patterns = [p for p in map(rendering_pattern, rendering.renderings) if p]
        for verse in sorted(rendering.denials):
            book, chapter, number = verse
            if verse not in verses_of[term_id]:
                yield Finding(book, f"{chapter}:{number}", WARNING, "term-lists", term_id,
                              f"the term '{term_id}' is marked OK without a rendering in a verse where it does not "
                              f"occur (maybe the verse numbers changed); remove the mark", "")
            elif verse in lower and any(p.search(lower[verse]) for p in patterns):
                yield Finding(book, f"{chapter}:{number}", WARNING, "term-lists", term_id,
                              f"the term '{term_id}' is marked OK without a rendering in this verse, but its "
                              f"rendering is here now; remove the mark", _context(usage.verse_texts[verse]))


MAX_RENDERING_WORDS = 5  # a longer rendering is a clause or a sentence, not a rendering of a term


def rendering_words(item: str) -> int:
    """Words of a rendering: comments "(…)" and "**" (any words) not counted."""
    text = re.sub(r"\([^)]*\)", " ", item).replace("**", " ")
    return sum(1 for word in text.split() if re.search(r"\w", word))


def check_term_renderings(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    """Renderings of more than 5 words: a clause, not a rendering. When a clause translates the term, the verse is
    marked OK without a rendering instead (the guide for technical managers)."""
    if _skipped(ctx, "term-renderings"):
        return
    data: TermData = ctx.terms
    ids = {term.id for term in data.terms}
    for term_id, rendering in data.renderings.items():
        if term_id not in ids:
            continue
        for item in rendering.renderings:
            words = rendering_words(item)
            if words > MAX_RENDERING_WORDS:
                yield Finding(PLACE, "(renderings)", WARNING, "term-renderings", item,
                              f"the rendering '{item}' of the term '{term_id}' has {words} words: a rendering is a word "
                              f"or a short phrase. If a clause translates the term, mark the verse OK without a "
                              f"rendering", "")
