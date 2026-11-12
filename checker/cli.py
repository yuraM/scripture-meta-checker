"""Command line entry point: run the checks over a Paratext project folder."""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

from checker.checks import (
    BOOK_CHECKS,
    CHECKS,
    ERROR,
    HYPHENATION_FILE,
    PROJECT_CHECKS,
    SOURCE_CHECKS,
    TERM_CHECKS,
    WARNING,
    CheckContext,
    Finding,
    UsageCounter,
)
from checker import places
from checker.books import book_from_file_name, book_order
from checker.html_report import HTML_FOLDER, TXT_FOLDER, CheckResult, Problem, write_html_report
from checker.hyphenation import load_hyphenation
from checker.languages import PROFILES, profile_for
from checker.parallels import PARALLEL_FILE, load_parallel_status
from checker.settings import load_settings
from checker.spelling import SpellingList, load_spelling_status
from checker.stages import STAGES, in_stage_order, stage_checks
from checker.structure import NumberForms, book_name_words
from checker.terms import load_terms
from checker.usfm import parse_usfm
from checker.versification import english_counts, project_to_original, verse_counts

ALL = "all"
# Checks run by default; project checks only when named.
TEXT_CHECKS = [*CHECKS, *BOOK_CHECKS, *SOURCE_CHECKS]

# Shown at the top of each report. Keep the English simple: many readers know little English.
CHECK_DESCRIPTIONS = {
    "untranslated-verses": "A verse that may be untranslated or in another language: most of its letters are in another alphabet than the project, or nearly all its words occur nowhere else in the project. Lists of rare words (animals, vices) can also be shown.",
    "apostrophes": "A sign between two letters (' ’ ʼ ʻ) that is not the one this project nearly always uses there "
                   "(for example ng'ombe among words with ʼ). Extra material (XXA…) is not checked: it is often in "
                   "another language.",
    "digit-systems": "Digits of another system than most numbers of the project (۲۷ among 27, or 1 among ၁). Numbers "
                     "inside text of another language (Copyright 1985) are not shown.",
    "fractions": "A fraction written with a slash (1/2) when most fractions of the project use the fraction slash "
                 "⁄ (U+2044): 1⁄2.",
    "self-references": "A cross reference \\x that points to the verse it stands in.",
    "one-chapter-books": "References to books with one chapter (Obadiah, Philemon, 2 and 3 John, Jude) written two "
                         "ways: with the chapter (Jude 1:3) and without it (Jude 3). The rare way is shown.",
    "term-renderings": "A rendering in Paratext Biblical Terms with more than 5 words. A rendering is a word or a "
                       "short phrase; if a clause translates the term, mark the verse OK without a rendering.",
    "poetry-numbers": "A number written with digits (12, or the digits of another script) in a poetry line "
                      "\\q, \\q1, \\q2. Poetry usually writes numbers in words. References (40:8) are not counted.",
    "footnote-quotes": "A footnote quotes the verse (\\fq), but a word of the quote is not in the verse: the quote or the verse was changed. Words with another ending count as found.",
    "line-ends": "A poetry line or a list item (\\li) ends with a comma or semicolon, and the next line starts with a capital letter of a word that is written small everywhere else: a full stop is missing, or the capital is wrong.",
    "poetry-long-lines": "A very long poetry line (longer than 99% of the poetry lines of this project and twice the usual length): maybe it should be two lines.",
    "poetry-verse-inside": "A verse number inside a poetry line. Poetry lines usually start with the verse.",
    "poetry-chapter-break": "Poetry goes on into the next chapter with no \b (stanza break) at the end of the chapter and no heading. Usually a new chapter is a new stanza: then add \b.",
    "poetry-two-sentences": "A long poetry line (longer than 95% of the poetry lines of this project) with a full "
                            "stop, ! or ? inside it: maybe it should be two lines. Two short sentences in one line "
                            "are normal.",
    "characters": f"Every character of the text must be marked correct in Paratext: {places.inventory(places.CHARACTERS)}. "
                  "'not allowed' = marked wrong there; 'not in the allowed list' = not marked yet.",
    "punctuation": "Punctuation between two words must be marked correct in Paratext: "
                   f"{places.inventory(places.PUNCTUATION)}. The sign _ means a space or the start/end of a paragraph. "
                   f"Signs between two numbers (6,8) come from {places.NUMBER_SETTINGS}.",
    "mixed-capitalization": "A word with a capital letter inside it (Bet-El) must be approved in Paratext Wordlist. "
                            f"Words marked wrong in {places.inventory(places.MIXED_CAPITALIZATION)} are errors.",
    "capitalization": "A sentence and a paragraph must start with a capital letter. Allowed cases are in Paratext: "
                      f"{places.inventory(places.PUNCTUATION_LOWERCASE)} and "
                      f"{places.inventory(places.MARKERS_LOWERCASE)}. Abbreviations: Settings.xml Abbreviations.",
    "spelling": "Every word must be approved in Paratext Wordlist (column Spelling). "
                "R = the word is right (green check), W = the word is wrong (red cross).",
    "quotes": "Every quote mark that opens must also close. "
              f"Quotes inside quotes must use the marks from Paratext: {places.QUOTATION_RULES}.",
    "pairs": "Every opening bracket must have a closing bracket (pairs from Settings.xml Pairs). "
             f"Exceptions: {places.inventory(places.UNMATCHED_PAIRS)}.",
    "repeated-words": "The same word two times in a row. Words marked correct or wrong in Paratext: "
                      f"{places.inventory(places.REPEATED_WORDS)}.",
    "spacing": f"Two spaces in a row, and the thousands separator in numbers (Paratext: {places.NUMBER_SETTINGS}).",
    "numbers": "Numbers with 4 digits must be written the same way in the whole text: with the thousands separator "
               f"(4 000) or without it (4000), as most of them are. The separator comes from {places.NUMBER_SETTINGS}. "
               "Book introductions are not counted, because they have many years (1446).",
    "scripts": "One word with letters from different alphabets, for example a Latin c in a Cyrillic word. "
               "These letters look the same, so they are hard to see.",
    "normalization": "The text must use the Unicode form from Settings.xml (NormalizationForm). "
                     "Usually you cannot see the difference.",
    "paragraph-final": "The last sign of a paragraph or heading. p_, means: paragraph \\p ends with a comma. "
                       "p alone means: paragraph \\p ends with a word (Final Punc '(none)'). Marked correct or wrong in "
                       f"Paratext: {places.inventory(places.FINAL_PUNCTUATION)}.",
    "ordinals": f"A number with an ending (5th) must be in the Ordinal list in Paratext: {places.NUMBER_SETTINGS}.",
    "usfm": "USFM markers and notes that are not closed, the order of chapters and verses, verses with no text, "
            f"footnote references to another verse (marks from Paratext: {places.REFERENCE_FORMAT}). "
            "Also the book of each file: one \\id, the same book as the file name, one file per book.",
    "book-titles": "The names of a book must agree. The long name \\toc1 is the main title: all \\mt lines in their "
                   "order in the file, for example \\mt2 + \\mt1 + \\mt3. The short name \\toc2 is the running header \\h. "
                   "A book number is written like in the other books: '1 Kings' or '1Kings' (\\h, \\toc1, \\toc2 "
                   "and \\toc3 each on their own). "
                   f"Book names: {places.BOOK_NAMES}.",
    "special-spaces": "Spaces that do not break a line. The narrow no-break space (U+202F) is used only between two "
                      "quotation marks, inside \\fv … \\fv* (\\fv 13 \\fv*Text, no space after \\fv*), and where the "
                      "project settings use it (numbers, reference marks). An abbreviation that the Abbreviations "
                      "list writes with ~ (the normal no-break space) is written the same way in the text. Between "
                      f"verse numbers after an abbreviation the marks come from {places.REFERENCE_FORMAT}.",
    "hyphenation": f"The list of word breaks {HYPHENATION_FILE} (Paratext Wordlist, column Hyphenation). "
                   "The sign = is a place where a line may break. The sign * means a person checked the entry.",
    "lists": "Paratext Wordlist, the checking inventories and the word breaks list must not disagree with each other. "
             "R = the word is right, W = the word is wrong.",
    "approvals": "Entries that a person marked correct (or wrong) in Paratext, but that look wrong: maybe they were "
                 "marked without looking. Also settings that turn a check off. Check each mark in the named window.",
    "variants": "A rare name is almost the same as a frequent name. It can be a typing mistake or another name.",
    "name-case": "A word is almost always written with a capital (or a small) letter, but here it is different. "
                 "Often this is on purpose (God / god).",
    "styled-words": "A word is almost always inside a marker such as \\nd (or outside it), but here it is different. "
                    "Often this is on purpose.",
    "divine-name": "The name of God (LORD) is not in \\nd in a verse where other translations have it in \\nd. "
                   "The check looks only at words that this project puts in \\nd nearly always.",
    "references": "References must point to a book, chapter and verse that exist, and use the marks from Paratext: "
                  f"{places.REFERENCE_FORMAT}. Book names: {places.BOOK_NAMES} (\\toc1-3).",
    "footnotes": "Footnotes that are built differently from similar footnotes of this project. The start of a "
                 "footnote (Lit.:) and the marker after it (\\fq = words of the verse, \\fqa = another reading) are "
                 "compared with the footnotes that start the same way. Also footnotes without an end mark (.) when "
                 "nearly all footnotes have one. The usual form and its count are in each message.",
    "unused": "Entries of the lists that are never used in the text. This is information only: usually it is no problem.",
    "parallel-changes": f"Verses that were approved in Paratext {places.PARALLEL_PASSAGES} (column Status), "
                        "but their words are different now. Check that the parallel verses still agree.",
    "parallel-differences": f"Parallel verses in different books (Paratext {places.PARALLEL_PASSAGES}) that differ in "
                            "only a few words. Often this is on purpose, because the original texts are different too.",
    "terms": "Biblical terms (Paratext Tools > Biblical Terms). Only clear cases are listed: a term is translated the "
             "same way in almost all its verses, but in this verse none of its renderings is found. Maybe the verse "
             "uses another word or has a typo. Also renderings that are not found anywhere in the text.",
    "term-lists": "The Biblical Terms lists themselves: verses marked OK without a rendering where the rendering is "
                  "there now, or where the term does not occur; renderings guessed by Paratext that no person "
                  "checked.",
}
LOCATION_HELP = ("How to read a place: GEN 3:14 = book, chapter:verse. 0:0 = book introduction. "
                 "12:0 = chapter 12 before verse 1. (2×) = two times in this place.")
SEVERITY_TITLES = {ERROR: "ERRORS: please fix these", WARNING: "WARNINGS: please look at these, some are not mistakes"}
SEPARATOR = "=" * 70


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a Paratext project against its own settings.")
    parser.add_argument("project", type=Path, help="project folder with Settings.xml, SpellingStatus.xml and *.SFM")
    parser.add_argument("--checks", nargs="+", choices=sorted([*TEXT_CHECKS, *PROJECT_CHECKS, ALL]),
                        help=f"checks to run (default: text checks; project checks {', '.join(PROJECT_CHECKS)} "
                             f"only when named, with '{ALL}' or with --stage)")
    parser.add_argument("--stage", nargs="+", type=int, choices=range(1, len(STAGES) + 1), metavar="N",
                        help="all checks of these stages, also with --checks: "
                             + "; ".join(title for title, _ in STAGES))
    parser.add_argument("--books", nargs="+", metavar="CODE", help="only these books, e.g. GEN MAT")
    parser.add_argument("--language", metavar="CODE",
                        help="language profile for language-specific rules (default: LanguageIsoCode from "
                             f"Settings.xml; known: {', '.join(sorted(PROFILES))}; anything else = generic rules)")
    parser.add_argument("--unique", action="store_true",
                        help="report each distinct problem once with its count and first location")
    parser.add_argument("--errors-only", action="store_true", help="hide warnings")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--output", type=Path, help="write the report to this file instead of stdout")
    output.add_argument("--report-dir", type=Path, help="write one report file per check into this folder")
    return parser


def book_code(content: str, path: Path) -> str:
    """Book code from the first \\id line (as in Paratext); without \\id the start of the file name."""
    match = re.search(r"\\id\s+(\S+)", content)
    return match.group(1).upper() if match else path.stem[:5]


def project_books(project: Path) -> list[tuple[str, str]]:
    """(book code, short name from \\toc2 or \\toc1) of every book file of a project, in Paratext book order."""
    settings = load_settings(project / "Settings.xml")
    books: dict[str, str] = {}
    for path in project.glob(f"{settings.file_name_pre_part}*{settings.file_name_post_part}"):
        with path.open(encoding="utf-8-sig", errors="replace") as file:
            head = file.read(4000)
        names = dict(re.findall(r"\\(toc[12])[ \t]+([^\r\n\\]+)", head))
        books.setdefault(book_code(head, path), (names.get("toc2") or names.get("toc1") or "").strip())
    return sorted(books.items(), key=lambda item: (book_order(item[0]), item[0]))


def missing_sources(ctx: CheckContext) -> dict[str, str]:
    """Checks that have nothing to check with: a file of the project is missing or empty, or the list in Paratext is
    empty. They are not run; the reports show "!" with the reason instead of 0 problems."""
    settings = ctx.settings
    hyphenation = ctx.hyphenation
    no_wordlist = not ctx.spelling.entries
    no_hyphenation = not hyphenation or not hyphenation.words
    reasons = {}
    if no_wordlist:
        for name in ("spelling", "mixed-capitalization"):
            reasons[name] = (f"Not checked: the {places.WORDLIST} is empty (SpellingStatus.xml is missing in the "
                             "project folder or has no words).")
    if no_hyphenation:
        reasons["hyphenation"] = (f"Not checked: {HYPHENATION_FILE} is missing or has no words (Paratext "
                                  f"{places.WORDLIST}, column Hyphenation).")
    if no_wordlist and no_hyphenation:
        reasons["lists"] = f"Not checked: the {places.WORDLIST} and {HYPHENATION_FILE} are both empty or missing."
    if not settings.valid_characters and not settings.invalid_characters:
        reasons["characters"] = f"Not checked: nothing is marked in {places.inventory(places.CHARACTERS)}."
    if not settings.valid_punctuation and not settings.invalid_punctuation:
        reasons["punctuation"] = f"Not checked: nothing is marked in {places.inventory(places.PUNCTUATION)}."
    if not settings.quote_levels:
        reasons["quotes"] = f"Not checked: the quotation marks are not set in Paratext ({places.QUOTATION_RULES})."
    if not settings.pairs:
        reasons["pairs"] = "Not checked: Settings.xml has no Pairs (brackets such as ( ) and [ ])."
    if not settings.number_ordinals:
        reasons["ordinals"] = f"Not checked: the Ordinal list is empty ({places.NUMBER_SETTINGS})."
    if not settings.normalization_form:
        reasons["normalization"] = "Not checked: Settings.xml has no NormalizationForm."
    return reasons


def run_checks(
    project: Path, checks: Sequence[str], books: Sequence[str] | None, language: str | None = None,
    skipped: dict[str, str] | None = None, progress: Callable[[int, int, str], None] | None = None,
    notes: dict[str, str] | None = None,
) -> Iterator[Finding]:
    """All findings; checks that could not run are added to `skipped` (check -> reason), notes of the checks
    (what was not listed) to `notes`.

    `progress(done, total, what)` is called before each book and before the project checks (for a window).
    """
    settings = load_settings(project / "Settings.xml")
    spelling_path = project / "SpellingStatus.xml"
    spelling = load_spelling_status(spelling_path) if spelling_path.exists() else SpellingList({})
    hyphenation_path = project / HYPHENATION_FILE
    hyphenation = load_hyphenation(hyphenation_path) if hyphenation_path.exists() else None
    profile = profile_for(language) if language is not None else None
    ctx = CheckContext(settings, spelling, hyphenation, profile)
    ctx.checks = frozenset(checks)
    if skipped is not None:
        ctx.skipped = skipped
    parallel_path = project / PARALLEL_FILE
    if parallel_path.exists():
        ctx.parallel_passages = load_parallel_status(parallel_path)
    if notes is not None:
        ctx.notes = notes
    ctx.to_original = project_to_original(project, settings.versification)
    ctx.verse_counts = verse_counts(project, settings.versification)
    ctx.english_counts = english_counts()
    for name, reason in missing_sources(ctx).items():
        if name in checks:
            ctx.skipped[name] = reason
    if any(name in TERM_CHECKS for name in checks):
        ctx.terms, ctx.terms_problem = load_terms(project, settings.biblical_terms_list, settings.versification)
    wanted = {code.upper() for code in books} if books else None
    usage = UsageCounter()

    pattern = f"{settings.file_name_pre_part}*{settings.file_name_post_part}"
    sources = [(path, path.read_text(encoding="utf-8-sig")) for path in sorted(project.glob(pattern))]
    ctx.book_name_words = frozenset(word for _, content in sources for word in book_name_words(content))
    ctx.book_title_words = frozenset(word for _, content in sources for word in book_name_words(content, names_only=True))
    ctx.book_number_forms = NumberForms()
    for _, content in sources:
        ctx.book_number_forms.add(content)
    file_of_book: dict[str, str] = {}
    for number, (path, content) in enumerate(sources):
        if progress:
            progress(number, len(sources) + 1, path.name)
        name_book = book_from_file_name(
            path.name, settings.file_name_pre_part, settings.file_name_post_part, settings.file_name_book_form)
        segments = parse_usfm(content, book=name_book or path.stem[:5])
        book = segments[0].book if segments else book_code(content, path)
        other_file = file_of_book.setdefault(book, path.name)
        # Every book is indexed, so references into books outside --books can be resolved.
        usage.add_source(book, content, ctx, with_references=not wanted or book in wanted)
        if wanted and book not in wanted:
            continue
        if other_file != path.name and "usfm" in checks:
            yield Finding(book, "0:0", ERROR, "usfm", f"{book} {path.name}",
                          f"the book {book} is in two files: {other_file} and {path.name}. "
                          "References to this book use the last file", "")
        for name in checks:
            if name in SOURCE_CHECKS and name not in ctx.skipped:
                yield from SOURCE_CHECKS[name](book, content, ctx, path.name)
        analyses = []
        for segment in segments:
            analysis = ctx.analyse(segment)
            analyses.append(analysis)
            usage.add(analysis, ctx)
            for name in checks:
                if name in CHECKS and name not in ctx.skipped:
                    yield from CHECKS[name](analysis, ctx)
        for name in checks:
            if name in BOOK_CHECKS and name not in ctx.skipped:
                yield from BOOK_CHECKS[name](analyses, ctx)

    if progress:
        progress(len(sources), len(sources) + 1, "checks of the whole project")
    for name in checks:
        if name in PROJECT_CHECKS and name not in ctx.skipped:
            yield from PROJECT_CHECKS[name](usage, ctx)
    if progress:
        progress(len(sources) + 1, len(sources) + 1, "done")


def short_reason(reason: str) -> str:
    """"Not checked: X. More." -> "not checked: X" for one line of a summary."""
    first = reason.split(". ")[0].rstrip(".")
    return first[:1].lower() + first[1:]


def format_locations(findings: Sequence[Finding]) -> str:
    """All locations, grouped by book: "MAT 27:46, 28:1 (2×); MRK 15:34"."""
    refs: dict[str, Counter[str]] = {}
    for f in findings:
        refs.setdefault(f.book, Counter())[f.ref] += 1
    return "; ".join(
        f"{book} " + ", ".join(ref if count == 1 else f"{ref} ({count}×)" for ref, count in counts.items())
        for book, counts in refs.items()
    )


def count_text(findings: Sequence[Finding]) -> str:
    errors = sum(f.severity == ERROR for f in findings)
    return f"errors: {errors}, warnings: {len(findings) - errors}"


def group_problems(findings: Sequence[Finding]) -> list[list[Finding]]:
    """Findings with the same message grouped: errors first, the most frequent first."""
    groups: dict[tuple[str, str], list[Finding]] = {}
    for f in findings:
        groups.setdefault((f.severity, f.message), []).append(f)
    return sorted(groups.values(), key=lambda group: (group[0].severity != ERROR, -len(group)))


def write_problems(findings: list[Finding], out) -> None:
    """Each distinct problem once, as a block of short lines: errors first, the most frequent first."""
    severity = None
    for number, group in enumerate(group_problems(findings), start=1):
        first = group[0]
        if first.severity != severity:
            severity = first.severity
            print(f"\n--- {SEVERITY_TITLES[severity]} ---", file=out)
        print(f"\n{number}. {first.message}", file=out)
        if len(group) > 1:
            print(f"   Found: {len(group)} times", file=out)
        if first.context:
            print(f"   Text:  {first.context.strip()}", file=out)
        print(f"   Where: {format_locations(group)}", file=out)


def write_check(name: str, findings: list[Finding], unique: bool, out, skipped: dict[str, str] | None = None,
                notes: dict[str, str] | None = None) -> None:
    print(f"CHECK: {name}", file=out)
    print(CHECK_DESCRIPTIONS.get(name, ""), file=out)
    if skipped and name in skipped:
        print(skipped[name], file=out)
        return
    print(count_text(findings).capitalize(), file=out)
    if notes and name in notes:
        print(notes[name], file=out)
    if not findings:
        return
    print(LOCATION_HELP, file=out)
    if unique:
        write_problems(findings, out)
    else:
        print(file=out)
        for f in findings:
            print(f.format(), file=out)


def write_report(findings: list[Finding], checks: Sequence[str], unique: bool, out,
                 skipped: dict[str, str] | None = None, notes: dict[str, str] | None = None) -> None:
    """All the given checks one after another, with a total when there is more than one."""
    skipped = skipped or {}
    selected = [(name, [f for f in findings if f.check == name]) for name in checks]
    for index, (name, group) in enumerate(selected):
        if index:
            print(f"\n{SEPARATOR}\n", file=out)
        write_check(name, group, unique, out, skipped, notes)
    if len(selected) > 1:
        print(f"\n{SEPARATOR}\n\nTOTAL", file=out)
        for name, group in selected:
            print(f"  {name:22} {'!  not checked' if name in skipped else count_text(group)}", file=out)
        print(f"  {'all checks':22} {count_text(findings)}", file=out)


def check_results(findings: Sequence[Finding], checks: Sequence[str],
                  skipped: dict[str, str], notes: dict[str, str] | None = None) -> list[CheckResult]:
    """Per check: counts and the grouped problems, for the HTML report and the window."""
    results = []
    for name in checks:
        selected = [f for f in findings if f.check == name]
        errors = sum(f.severity == ERROR for f in selected)
        problems = [Problem(group[0].severity, group[0].message, len(group), group[0].context.strip(),
                            format_locations(group), group[0].item) for group in group_problems(selected)]
        results.append(CheckResult(name, CHECK_DESCRIPTIONS.get(name, ""), errors, len(selected) - errors,
                                   skipped.get(name, ""), problems, (notes or {}).get(name, "")))
    return results


RUN_FOLDER_FORMAT = "%Y-%m-%d_%H-%M"  # one folder per run: <project>_report/2026-11-03_14-05/
_RUN_FOLDER_RE = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}(?:_\d+)?$")


def new_run_folder(report_dir: Path) -> Path:
    """A new folder for the reports of one run, named by date and time, inside `report_dir`.

    Reports of older versions lay directly in `report_dir` (<check>.txt, <check>.html, index.html, html/, txt/):
    they are removed, other files there are kept.
    """
    report_dir.mkdir(parents=True, exist_ok=True)
    for name in CHECK_DESCRIPTIONS:
        for old in (report_dir / f"{name}.txt", report_dir / f"{name}.html",
                    report_dir / TXT_FOLDER / f"{name}.txt", report_dir / HTML_FOLDER / f"{name}.html"):
            old.unlink(missing_ok=True)
    (report_dir / "index.html").unlink(missing_ok=True)
    for folder in (report_dir / TXT_FOLDER, report_dir / HTML_FOLDER):
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    stamp = datetime.now().strftime(RUN_FOLDER_FORMAT)
    run = report_dir / stamp
    number = 2
    while run.exists():  # two runs in the same minute
        run = report_dir / f"{stamp}_{number}"
        number += 1
    run.mkdir()
    return run


def latest_run(report_dir: Path) -> Path | None:
    """The newest run folder with a report (by its name, which is the date and time), or None."""
    if not report_dir.is_dir():
        return None
    runs = [p for p in report_dir.iterdir() if p.is_dir() and _RUN_FOLDER_RE.match(p.name) and (p / "index.html").is_file()]
    return max(runs, key=lambda p: (p.name[:16], int(p.name[17:] or 1)), default=None)


def write_reports(project: Path, findings: list[Finding], checks: Sequence[str], report_dir: Path, unique: bool,
                  skipped: dict[str, str], notes: dict[str, str] | None = None) -> list[CheckResult]:
    """The reports in `report_dir` (the folder of one run): index.html, html/<check>.html and txt/<check>.txt."""
    txt_dir = report_dir / TXT_FOLDER
    txt_dir.mkdir(parents=True, exist_ok=True)
    for name in checks:
        selected = [f for f in findings if f.check == name]
        with (txt_dir / f"{name}.txt").open("w", encoding="utf-8") as out:
            write_report(selected, [name], unique, out, skipped, notes)
    results = check_results(findings, checks, skipped, notes)
    # Links to Paratext name the project as Paratext windows do (Settings.xml <Name>), with its versification.
    settings_path = project / "Settings.xml"
    settings = load_settings(settings_path) if settings_path.is_file() else None
    link = {"project": settings.name or project.resolve().name, "vrs": settings.versification} if settings else None
    write_html_report(report_dir, project.resolve().name, results, LOCATION_HELP, link)
    return results


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.checks and ALL in args.checks:
        checks = [*TEXT_CHECKS, *PROJECT_CHECKS]
    elif args.checks or args.stage:
        checks = [*(args.checks or []), *stage_checks(args.stage or [])]
    else:
        checks = TEXT_CHECKS
    checks = in_stage_order(checks)
    skipped: dict[str, str] = {}
    notes: dict[str, str] = {}
    findings = list(run_checks(args.project, checks, args.books, args.language, skipped, notes=notes))
    if args.errors_only:
        findings = [f for f in findings if f.severity == ERROR]

    if args.report_dir:
        run = new_run_folder(args.report_dir)
        results = write_reports(args.project, findings, checks, run, args.unique, skipped, notes)
        for result in results:
            counts = (f"     !  {short_reason(result.skipped)}" if result.skipped
                      else f"{result.errors:6} errors {result.warnings:7} warnings")
            print(f"{result.name:22} {counts}  -> {run / TXT_FOLDER / (result.name + '.txt')}")
        print(f"HTML report: {run / 'index.html'}")
    elif args.output:
        with args.output.open("w", encoding="utf-8") as out:
            write_report(findings, checks, args.unique, out, skipped, notes)
    else:
        write_report(findings, checks, args.unique, sys.stdout, skipped, notes)
    return 1 if any(f.severity == ERROR for f in findings) else 0
