"""Run the Paratext project checker.

Edit the settings below and run this file (Shift+F10 in PyCharm).
Command line arguments, if given, override these settings: `python main.py --help`.
"""
import sys
from pathlib import Path

from checker.cli import main

# ---------------------------------------------------------------- settings ---

# Paratext project folder (Settings.xml, SpellingStatus.xml, hyphenatedWords.txt, *.SFM): put your folder here.
# For everyday use the window (checker_app.py / checker.exe) is easier: it lists the Paratext projects.
PROJECT = Path(__file__).parent / "MyProject"

# Comment out the checks you do not need.1
CHECKS = [
    "characters",            # ValidCharacters / InvalidCharacters
    "punctuation",           # ValidPunctuation / InvalidPunctuation
    "mixed-capitalization",  # mixed-case words approved in SpellingStatus.xml
    "capitalization",        # capital after sentence end, abbreviations
    "spelling",              # SpellingStatus.xml
    "quotes",                # quotation marks: unclosed, wrong level, mismatched
    "pairs",                 # Pairs: ( ) [ ] { } unclosed or mismatched
    "repeated-words",        # "і і"; RepeatableWords / NonRepeatableWords
    "spacing",               # double spaces, thousands separator in numbers
    "numbers",               # 4-digit numbers written in the rare way of the project (4000 among 4.000)
    "scripts",               # words mixing scripts (Latin "c" in a Cyrillic word)
    "apostrophes",           # the rare apostrophe of the project between two letters (' among ʼ)
    "digit-systems",         # digits of another system than most numbers (۲۷ among 27)
    "fractions",             # 1/2 where the project writes 1⁄2
    "normalization",         # NormalizationForm (NFC)
    "paragraph-final",       # last punctuation of a paragraph; headings ending with "."
    "ordinals",              # NumberOrdinals: "5-го", "8th", "ke-430"
    "usfm",                  # unclosed markers and notes, chapter/verse numbering, empty verses, \fr vs verse
    "untranslated-verses",   # verse left in another language (other alphabet, words found nowhere else)
    "book-titles",           # \toc1 = \mt2 + \mt1, \toc2 = \h
    "special-spaces",        # narrow no-break space U+202F, "\fv 13 \fv*", н.~э., marks in verse lists
    "hyphenation",           # hyphenatedWords.txt: rules, consistency, missing words
    "lists",                 # contradictions between SpellingStatus, Settings and hyphenation lists
    "approvals",             # approved list entries that look wrong; rejected ones used very often
    "variants",              # rare names one letter away from a frequent one (Петор / Петро)
    "name-case",             # word usually capitalized mid-sentence but not here (or the reverse)
    "styled-words",          # word usually in \nd but not here (or the reverse)
    "divine-name",           # the divine name without \nd where translations have LORD in \nd
    "poetry-numbers",        # digits in poetry lines \q1 \q2 (poetry usually writes numbers in words)
    "line-ends",             # poetry/list line ends with "," but the next starts with a capital (full stop?)
    "poetry-two-sentences",  # long poetry line with a sentence end inside: maybe two lines
    "poetry-long-lines",     # very long poetry line
    "poetry-verse-inside",   # verse number inside a poetry line
    "poetry-chapter-break",  # poetry goes on into the next chapter without 
    "references",            # references: chapters/verses that do not exist, marks not from Settings.xml
    "self-references",       # cross reference \x to the verse it stands in
    "one-chapter-books",     # Jude 1:3 and Jude 3 in one project
    "footnotes",             # footnotes built differently from similar ones (Lit.: \fq vs \fqa, missing full stop)
    "footnote-quotes",       # \fq quote of a footnote not found in the verse
    "parallel-changes",      # ParallelPassageStatus.xml: approved parallel verses that were changed later
    "parallel-differences",  # ParallelPassageStatus.xml: parallel verses that differ in a few words
    "terms",                 # Biblical Terms: rendering missing in a verse (clear cases only), unused renderings
    "term-lists",            # Biblical Terms: old 'OK without a rendering' marks, guessed renderings
    "term-renderings",       # Biblical Terms: renderings of more than 5 words
    "unused",                # list entries that never occur in the text (large report)
]

# Only these books, e.g. ["GEN", "MAT"]; None = all books.
BOOKS = None

# Language profile for language-specific rules, e.g. "uk"; None = LanguageIsoCode from Settings.xml.
LANGUAGE = None

# Folder for the reports: one file per check (<project>_report/spelling.txt, ...); None = print to the console.
REPORT_DIR = PROJECT.parent / f"{PROJECT.name}_report"

UNIQUE = True        # each distinct problem once, with its count and first location
ERRORS_ONLY = False  # hide warnings

# -----------------------------------------------------------------------------


def settings_to_args() -> list[str]:
    args = [str(PROJECT), "--checks", *CHECKS]
    if BOOKS:
        args += ["--books", *BOOKS]
    if LANGUAGE:
        args += ["--language", LANGUAGE]
    if REPORT_DIR:
        args += ["--report-dir", str(REPORT_DIR)]
    if UNIQUE:
        args.append("--unique")
    if ERRORS_ONLY:
        args.append("--errors-only")
    return args


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or settings_to_args()))
