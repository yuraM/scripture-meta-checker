"""The individual checks. Each check takes an analysed segment and yields findings."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from functools import lru_cache

from checker import places
from checker.forms import (
    check_all_caps, check_apostrophes, check_dashes, check_digit_systems, check_ellipses, check_fractions, check_heading_case,
    check_marker_capitals, check_note_callers, check_untranslated,
)
from checker.verses import check_figures, check_glossary_words, check_repeated_text, check_verse_lengths
from checker.poetry import (
    check_poetry_chapter_break, check_line_ends, check_poetry_long_lines, check_poetry_numbers,
    check_poetry_two_sentences, check_poetry_verse_inside, is_poetry_line,
)
from checker.approvals import check_approvals
from checker.divine_name import VerseNd, check_divine_name, usual_nd_words
from checker.footnotes import Note, check_footnote_quotes, check_footnotes, read_notes
from checker.hyphenation import inconsistent_affixes, is_unhyphenated, rule_violations, word_scripts
from checker.model import ERROR, WARNING, Analysis, CheckContext, Finding  # noqa: F401 (re-exported)
from checker.pairs import check_pairs
from checker.parallels import check_parallel_changes, check_parallel_differences
from checker.quotes import check_quotes, is_isolated
from checker.references import ReferencePart, parse_reference
from checker.settings import ReferenceFormat
from checker.spelling import STATE_RIGHT, STATE_WRONG
from checker.books import book_from_file_name
from checker.spaces import check_special_spaces
from checker.terms import check_term_lists, check_term_renderings, check_terms
from checker.structure import (
    PERIPHERAL_BOOKS, XtReference, check_book_titles, check_file, check_structure, index_book, verse_range,
)
from checker.tokens import LETTER, Run, graphemes, punctuation_pattern, single_edit
from checker.usfm import Segment

HYPHENATION_FILE = "hyphenatedWords.txt"
MAX_LISTED_UNREVIEWED = 100
# Numbers with at least this many digits need a thousands separator.
MIN_SEPARATED_DIGITS = 5
# Poetry and list lines often end mid-sentence: for them only InvalidParagraphFinalPunctuationItems is used.
VERSE_LINE_STYLE_PREFIXES = ("q", "li", "lh", "lf", "lim")
NORMALIZATION_FORMS = frozenset({"NFC", "NFD", "NFKC", "NFKD"})
# Section headings (\s1, \ms2, ...): no full stop, comma or colon at the end.
HEADING_STYLE_RE = re.compile(r"(?:s|ms)\d*$")
HEADING_FORBIDDEN_FINAL = ("FULL STOP", "COMMA", "COLON")
# variants: a word occurring at most VARIANT_MAX_RARE times next to one VARIANT_MIN_RATIO times more frequent.
VARIANT_MIN_LENGTH = 5
VARIANT_MAX_RARE = 3
VARIANT_MIN_RATIO = 10
VARIANT_IGNORED_ENDING = 2  # edits in the last letters are inflection, not a variant
# name-case / styled-words: the form used in at most MINORITY_SHARE of >= MIN_OCCURRENCES occurrences.
CONSISTENCY_MIN_OCCURRENCES = 10
CONSISTENCY_MINORITY_SHARE = 0.05
# Character styles a word should use consistently (\nd for the divine name).
STYLE_CONSISTENCY_MARKERS = ("nd",)
# Link attributes ("8-му|GEN 2:8") are USFM: always a book code and ":", in every language.
LINK_FORMAT = ReferenceFormat()
LINK_BOOK_RE = re.compile(r"([0-9A-Z]{3})\s+\d")
BOOK_NAME_BEFORE_NUMBER_RE = re.compile(rf"(?:\d+\s?)?{LETTER}+(?:[-‐‑'’]{LETTER}+)*\.?\s+(?=\d)")
EDIT_NAMES = {"substitution": "one letter is different", "insertion": "one letter more or less",
              "transposition": "two letters are swapped"}


def _describe(cluster: str) -> str:
    codes = " ".join(f"U+{ord(ch):04X}" for ch in cluster)
    names = " + ".join(unicodedata.name(ch, "UNKNOWN") for ch in cluster)
    return f"'{cluster}' ({codes} {names})"


def check_characters(analysis: Analysis, ctx: CheckContext) -> Iterator[Finding]:
    valid = ctx.settings.valid_characters
    invalid = ctx.settings.invalid_characters
    for offset, cluster in graphemes(analysis.segment.text):
        if cluster == " " or cluster in valid:
            continue
        if cluster in invalid or cluster[0] in invalid:
            yield analysis.finding(offset, len(cluster), ERROR, "characters", cluster,
                                   f"this character is not allowed: {_describe(cluster)}")
        else:
            yield analysis.finding(offset, len(cluster), WARNING, "characters", cluster,
                                   f"this character is not in the allowed list: {_describe(cluster)}")


def is_number_separator(runs: list[Run], index: int, ctx: CheckContext) -> bool:
    """The run is a separator between two digits ("6,8", "12:5"), not punctuation between words, or a mark of a
    Scripture reference ("5:1‒3" with "‒" in Reference Format)."""
    if not (0 < index < len(runs) - 1 and runs[index + 1].text[0].isdigit()):
        return False
    if runs[index - 1].text[-1].isdigit() and runs[index].text in ctx.settings.number_medial_punctuation:
        return True
    return _in_reference(runs, index, ctx)  # also after a verse part: "12:31б‒13:13"


# Runs looked at before a mark to see whether it stands in a reference.
REFERENCE_LOOK_BACK = 40


@lru_cache(maxsize=8)
def _reference_patterns(
    reference_format: ReferenceFormat,
) -> tuple[frozenset[str], re.Pattern[str], re.Pattern[str]]:
    """Marks of references (Reference Format, without words such as "and") and the text a mark may follow in a
    reference: "12:5", "12:5‒7, 9", "2:1‒7:10"; or a book name (group 1) and chapters: "Пар. 22", "Пар. 22‒26; 28"."""
    marks = {mark.strip() for marks in (reference_format.verse_ranges, reference_format.verse_sequences,
                                        reference_format.chapter_ranges, reference_format.chapter_sequences)
             for mark in marks}
    marks = frozenset(mark for mark in marks if mark and not any(ch.isalnum() for ch in mark))
    separator = re.escape(reference_format.chapter_verse)
    number = r"\d+[^\W\d_]?"  # 12 or 12б (a verse part)
    any_mark = "|".join(re.escape(mark) for mark in sorted(marks | {reference_format.chapter_verse}, key=len,
                                                            reverse=True))
    more = rf"(?:\s?(?:{any_mark})\s?{number})*"
    return (marks, re.compile(rf"\d+\s?{separator}\s?{number}{more}$"),
            re.compile(rf"({LETTER}+)\.?[\s~]{number}{more}$"))


def _in_reference(runs: list[Run], index: int, ctx: CheckContext) -> bool:
    """The run is a mark of Reference Format standing in a reference: after "chapter:verse" ("5:1‒3", "5:1, 3‒4",
    "2:1‒7:10") or after a book name and a number ("Psalms 1–41", "Быт. 6‒8")."""
    marks, after, after_book = _reference_patterns(ctx.settings.reference_format)
    if runs[index].text.strip() not in marks:
        return False
    before = "".join(run.text for run in runs[max(index - REFERENCE_LOOK_BACK, 0):index])
    if after.search(before):
        return True
    book = after_book.search(before)
    return bool(book) and book.group(1).lower() in _single_words(ctx.book_title_words)


@lru_cache(maxsize=8)
def _single_words(words: frozenset[str]) -> frozenset[str]:
    """Book name words split at spaces: "1~Пар." is kept as "1 пар", the text has "Пар." after "1~"."""
    return frozenset(part for word in words for part in word.split())


def check_punctuation(analysis: Analysis, ctx: CheckContext) -> Iterator[Finding]:
    valid = ctx.settings.valid_punctuation
    invalid = ctx.settings.invalid_punctuation
    runs = analysis.runs
    text_length = len(analysis.segment.text)
    for index, run in enumerate(runs):
        if run.is_word or run.text.isspace():
            continue
        if is_number_separator(runs, index, ctx):
            continue
        pattern = punctuation_pattern(run, text_length)
        if pattern in invalid:
            yield analysis.finding(run.start, len(run.text), ERROR, "punctuation", pattern,
                                   f"this punctuation is not allowed: '{pattern}'")
        elif pattern not in valid:
            yield analysis.finding(run.start, len(run.text), WARNING, "punctuation", pattern,
                                   f"this punctuation is not in the allowed list: '{pattern}'")


def _is_mixed_case(word: str) -> bool:
    return any(ch.isupper() for ch in word[1:]) and not word.isupper()


def _is_approved_form(word: str, ctx: CheckContext) -> bool:
    """The exact form is approved in SpellingStatus.xml: an R entry keyed by it or listing it as SpecificCase."""
    entry = ctx.spelling.lookup(word)
    return bool(entry) and entry.state == STATE_RIGHT and (word == entry.word or word in entry.specific_cases)


def _mixed_case_problem(word: str, ctx: CheckContext) -> bool:
    """check_mixed_capitalization reports `word` (an error or a warning)."""
    return (_is_mixed_case(word) and not any(ch.isdigit() for ch in word)
            and (word in ctx.settings.invalid_mixed_capitalization or not _is_approved_form(word, ctx)))


def _spelling_note(ctx: CheckContext) -> None:
    parts = []
    if ctx.skipped_book_words:
        parts.append(f"Not checked: {len(ctx.skipped_book_words)} words of book names (\\toc1-3), "
                     f"e.g. {', '.join(sorted(ctx.skipped_book_words)[:8])}.")
    if ctx.mixed_case_words:
        count = len(ctx.mixed_case_words)
        parts.append(f"Not listed here: {count} {'word' if count == 1 else 'words'} with a capital letter inside, "
                     f"e.g. {', '.join(sorted(ctx.mixed_case_words)[:8])}. They are in the report mixed-capitalization.")
    ctx.notes["spelling"] = " ".join(parts)


def check_mixed_capitalization(analysis: Analysis, ctx: CheckContext) -> Iterator[Finding]:
    # Settings.xml ValidMixedCapitalization is outdated and deliberately ignored;
    # SpellingStatus.xml decides which mixed-case forms are valid.
    for word in analysis.words:
        # Words with digits are references/abbreviations such as "1Sa", not mixed capitalization.
        if not _mixed_case_problem(word.text, ctx):
            continue
        if word.text in ctx.settings.invalid_mixed_capitalization:
            yield analysis.finding(word.start, len(word.text), ERROR, "mixed-capitalization", word.text,
                                   f"capital letter inside a word is not allowed: '{word.text}'")
        else:
            yield analysis.finding(word.start, len(word.text), WARNING, "mixed-capitalization", word.text,
                                   f"capital letter inside a word, not approved in {places.WORDLIST}: '{word.text}'")


def check_capitalization(analysis: Analysis, ctx: CheckContext) -> Iterator[Finding]:
    """Paragraph-initial capitals and capitals after sentence-final punctuation (abbreviations excepted)."""
    settings = ctx.settings
    segment = analysis.segment
    runs = analysis.runs

    first_word = next((run for run in runs if run.is_word), None)
    if (
        first_word
        and not segment.in_note
        and segment.style in settings.invalid_uncapitalized_styles
        and first_word.text[0].islower()
    ):
        yield analysis.finding(first_word.start, len(first_word.text), WARNING, "capitalization",
                               segment.style, f"\\{segment.style} paragraph starts with a small letter: "
                                              f"'{first_word.text}'")

    for index in range(1, len(runs) - 1):
        gap, previous, following = runs[index], runs[index - 1], runs[index + 1]
        if gap.is_word or not previous.is_word or not following.text[0].islower():
            continue
        last_final = max((i for i, ch in enumerate(gap.text) if ch in settings.sentence_final_punctuation),
                         default=-1)
        if last_final < 0 or not any(ch.isspace() for ch in gap.text[last_final:]):
            continue
        sequence = " ".join(gap.text.split())
        if sequence in settings.valid_sentence_final_capitalization:
            continue
        if gap.text.startswith(".") and f"{previous.text}.".lower() in ctx.abbreviations:
            continue
        yield analysis.finding(following.start, len(following.text), WARNING, "capitalization", sequence,
                               f"small letter at the start of a sentence: '{following.text}' after '{sequence}'")


def check_spelling(analysis: Analysis, ctx: CheckContext) -> Iterator[Finding]:
    for word in analysis.words:
        if any(ch.isdigit() for ch in word.text):
            continue
        # Words of book names (\toc1-3) are set by the project itself; a W mark on one is reported once by `lists`.
        if word.text.lower() in ctx.book_title_words:
            if word.text.lower() not in ctx.skipped_book_words:
                ctx.skipped_book_words.add(word.text.lower())
                _spelling_note(ctx)
            continue
        entry = ctx.spelling.lookup(word.text)
        # A capital inside the word: mixed-capitalization shows it, unless the list marks the word wrong (W).
        if ("mixed-capitalization" in ctx.checks and (entry is None or entry.state != STATE_WRONG)
                and _mixed_case_problem(word.text, ctx)):
            if word.text not in ctx.mixed_case_words:
                ctx.mixed_case_words.add(word.text)
                _spelling_note(ctx)
            continue
        if entry is None:
            similar = ctx.spelling.similar(word.text)
            hint = f" (similar approved words: {', '.join(f"'{w}'" for w in similar)})" if similar else ""
            yield analysis.finding(word.start, len(word.text), WARNING, "spelling", word.text,
                                   f"word is not approved in {places.WORDLIST}: '{word.text}'{hint}")
        elif entry.state == STATE_WRONG and (lowercase := ctx.spelling.entries.get(word.text.lower())) \
                and lowercase is not entry and lowercase.state == STATE_RIGHT:
            # A capitalized W key next to an approved lowercase key (e.g. "Дивіться" W / "дивіться" R)
            # is a contradiction in the list, not proof that the text is wrong.
            yield analysis.finding(word.start, len(word.text), WARNING, "spelling", word.text,
                                   f"{places.WORDLIST} disagrees with itself: '{entry.word}' is wrong (W), "
                                   f"'{lowercase.word}' is right (R)")
        elif entry.state == STATE_WRONG:
            suggestion = f" (use: {', '.join(f"'{c}'" for c in entry.corrections)})" if entry.corrections else ""
            yield analysis.finding(word.start, len(word.text), ERROR, "spelling", word.text,
                                   f"word is marked wrong in {places.WORDLIST}: '{word.text}'{suggestion}")
        elif entry.state != STATE_RIGHT:
            yield analysis.finding(word.start, len(word.text), WARNING, "spelling", word.text,
                                   f"word has an unknown state '{entry.state}' in {places.WORDLIST}: '{word.text}'")
        elif (
            entry.specific_cases
            and word.text not in entry.specific_cases
            and not word.text.isupper()
            # An all-caps approved form ("TUHAN") is how small-caps styles such as
            # \nd render the word, so "\nd Tuhan\nd*" matches it.
            and word.text.upper() not in entry.specific_cases
        ):
            # SpecificCase records the approved form(s); often just a sentence-initial capital,
            # so a different case is only suspicious, not necessarily wrong.
            yield analysis.finding(word.start, len(word.text), WARNING, "spelling", word.text,
                                   f"capital or small letters are different: '{word.text}', {places.WORDLIST} has: "
                                   f"{' / '.join(f"'{c}'" for c in entry.specific_cases)}")


def check_repeated_words(analysis: Analysis, ctx: CheckContext) -> Iterator[Finding]:
    """The same word twice in a row ("і і"), separated by whitespace only."""
    text = analysis.segment.text
    words = analysis.words
    for previous, word in zip(words, words[1:]):
        if word.text.lower() != previous.text.lower() or not text[previous.end:word.start].isspace():
            continue
        forms = {word.text, previous.text, word.text.lower()}
        pair = text[previous.start:word.end]
        if forms & ctx.non_repeatable_words:
            yield analysis.finding(previous.start, len(pair), ERROR, "repeated-words", word.text.lower(),
                                   f"word is written twice: '{pair}' (marked wrong in {places.REPEATED_WORDS})")
        elif not forms & ctx.repeatable_words:
            yield analysis.finding(previous.start, len(pair), WARNING, "repeated-words", word.text.lower(),
                                   f"word is written twice: '{pair}'")


def _codes(text: str) -> str:
    return " + ".join(f"U+{ord(ch):04X}" for ch in text)


def _separator_text(separator: str) -> str:
    return _codes(separator) if separator.isspace() else f"'{separator}'"


def _numbers(text: str, ctx: CheckContext) -> Iterator[re.Match]:
    """Numbers of the text, with the thousands separator inside them ("10 000"). Not the digits after a reference
    or fraction mark ("3:16", "1,5"): they belong to the number before."""
    separator = ctx.settings.number_thousands_separator
    not_after = ctx.settings.number_medial_punctuation - {separator}
    for match in re.finditer(rf"\d+(?:{re.escape(separator)}\d+)*", text):
        start = match.start()
        if start >= 2 and text[start - 2].isdigit() and (text[start - 1] in not_after or text[start - 1].isspace()):
            continue
        yield match


def four_digit_form(number: str, separator: str) -> bool | None:
    """True = "4 000" (with the separator), False = "4000", None = not a 4-digit number."""
    groups = number.split(separator)
    if len(groups) == 1 and len(number) == 4:
        return False
    if len(groups) == 2 and len(groups[0]) == 1 and len(groups[1]) == 3:
        return True
    return None


def _groups_ok(groups: list[str], hindi_urdu: bool) -> bool:
    """Digit groups of a number with thousands separators: "144,000" or, with HindiUrduNumberGrouping, "1,44,000"."""
    if hindi_urdu:
        return (len(groups[-1]) == 3 and 1 <= len(groups[0]) <= 2
                and all(len(group) == 2 for group in groups[1:-1]))
    return len(groups[0]) <= 3 and all(len(group) == 3 for group in groups[1:])


def _is_range_or_list_mark(ch: str, ctx: CheckContext) -> bool:
    """A mark between two numbers of a reference or a list: a dash (Unicode Pd, "103–105"), the chapter-verse
    mark, a mark of NumberMedialPunctuation, or the thousands separator itself ("605, 597")."""
    settings = ctx.settings
    return (unicodedata.category(ch) == "Pd" or ch in settings.chapter_verse_separator
            or ch in settings.number_medial_punctuation or ch == settings.number_thousands_separator)


def _split_number(text: str, match: re.Match, in_note: bool, ctx: CheckContext) -> str:
    """"1, 44,000", "45, 000": one number with a space after the thousands separator; returns that text or "".
    Lists and references are not split numbers: "605, 597, 586", "119:9–21, 103–105", "aya 65, 169" (a note).
    A second part of 3 digits only ("45, 400") counts as "000", or after 1-2 digits outside notes
    ("458, 445" = years)."""
    separator = ctx.settings.number_thousands_separator
    if separator.isspace():
        return ""
    sep = re.escape(separator)
    split = re.compile(rf"{sep}[^\S\n]+(\d+(?:{sep}\d+)*)(?!\d)").match(text, match.end())
    if not split:
        return ""
    first, second, start = match.group(), split.group(1), match.start()
    if not _groups_ok((first + separator + second).split(separator), ctx.settings.hindi_urdu_grouping):
        return ""
    if separator not in second and second != "000" and (len(first) > 2 or in_note):
        return ""
    before = re.search(r"\d[^\S\n]*(\S)[^\S\n]*$", text[max(0, start - 10):start])
    after = re.match(r"[^\S\n]*(\S)[^\S\n]*\d", text[split.end():])
    if any(mark and _is_range_or_list_mark(mark.group(1), ctx) for mark in (before, after)):
        return ""
    return text[start:split.end()]


def check_spacing(analysis: Analysis, ctx: CheckContext) -> Iterator[Finding]:
    """Double spaces and thousands separators in numbers (NumberThousandsSeparator)."""
    text = analysis.segment.text
    for match in re.finditer(r"\s{2,}", text):
        yield analysis.finding(match.start(), len(match.group()), WARNING, "spacing", "double space",
                               f"two spaces in a row ({_codes(match.group())})")

    separator = ctx.settings.number_thousands_separator
    if not separator:
        return
    shown = _separator_text(separator)
    hindi_urdu = ctx.settings.hindi_urdu_grouping
    for match in _numbers(text, ctx):
        number, start = match.group(), match.start()
        groups = number.split(separator)
        if len(groups) == 1 and len(number) >= MIN_SEPARATED_DIGITS:
            yield analysis.finding(start, len(number), WARNING, "spacing", "no thousands separator",
                                   f"number '{number}' needs a thousands separator {shown}")
        elif len(groups) > 1 and not _groups_ok(groups, hindi_urdu):
            rule = ("the digit groups must have 2 digits, and the last group 3 digits" if hindi_urdu
                    else "after the thousands separator there must be 3 digits")
            yield analysis.finding(start, len(number), WARNING, "spacing", "digit groups",
                                   f"number '{number}': {rule}")
        split = _split_number(text, match, analysis.segment.in_note, ctx)
        if split:
            yield analysis.finding(start, len(split), WARNING, "spacing", "space in number",
                                   f"number '{split}' has a space after the thousands separator {shown}")
        # "10 000" with an ordinary space instead of the separator.
        following = re.match(r"(\s)(\d{3})(?!\d)", text[match.end():])
        if following and following.group(1) != separator and len(groups[-1]) <= 3:
            wrong = number + following.group()
            yield analysis.finding(start, len(wrong), WARNING, "spacing", "wrong thousands separator",
                                   f"number '{wrong}' uses {_codes(following.group(1))} "
                                   f"instead of the thousands separator {shown}")


def _script(ch: str) -> str:
    return next(iter(word_scripts(ch)), "")


def check_scripts(analysis: Analysis, ctx: CheckContext) -> Iterator[Finding]:
    """A word mixing writing systems, e.g. Cyrillic "cлово" with a Latin "c"."""
    for word in analysis.words:
        scripts = word_scripts(word.text)
        if len(scripts) < 2:
            continue
        main = Counter(_script(ch) for ch in word.text if _script(ch)).most_common(1)[0][0]
        foreign = dict.fromkeys(ch for ch in word.text if _script(ch) not in ("", main))
        yield analysis.finding(word.start, len(word.text), ERROR, "scripts", word.text,
                               f"word '{word.text}' has letters from different alphabets ({' + '.join(sorted(scripts))}): "
                               f"{', '.join(_describe(ch) for ch in foreign)} in a {main} word")


def check_normalization(analysis: Analysis, ctx: CheckContext) -> Iterator[Finding]:
    """Text not in the Unicode normalization form required by Settings.xml (NormalizationForm)."""
    form = ctx.settings.normalization_form
    if form not in NORMALIZATION_FORMS or unicodedata.is_normalized(form, analysis.segment.text):
        return
    for run in analysis.runs:
        if not unicodedata.is_normalized(form, run.text):
            yield analysis.finding(run.start, len(run.text), ERROR, "normalization", run.text,
                                   f"'{run.text}' ({_codes(run.text)}) is not in Unicode form {form}, it should be "
                                   f"{_codes(unicodedata.normalize(form, run.text))}")


def paragraph_ending(segment: Segment, ctx: CheckContext) -> tuple[str, int] | None:
    """Paragraph-final item and the offset after its last sign; closing quotes and brackets are skipped.

    Items are "<style>_<punctuation>", or just "<style>" for a paragraph ending with a word. None for notes.
    """
    if segment.in_note or not segment.style:
        return None
    end = len(segment.text)
    while end and (segment.text[end - 1] in ctx.closing_marks or segment.text[end - 1].isspace()):
        end -= 1
    if not end:
        return None
    last = segment.text[end - 1]
    return (segment.style if ctx.is_word_char(last) else f"{segment.style}_{last}"), end


def check_paragraph_final(analysis: Analysis, ctx: CheckContext) -> Iterator[Finding]:
    """Last punctuation of a paragraph (closing quotes and brackets skipped) against
    Valid/InvalidParagraphFinalPunctuationItems and MarkersRequiringSentenceFinalPunctuation."""
    settings = ctx.settings
    segment = analysis.segment
    ending = paragraph_ending(segment, ctx)
    if not ending:
        return
    item, end = ending
    style, last = segment.style, segment.text[end - 1]
    if HEADING_STYLE_RE.match(style):
        # Matched by Unicode name, so "?" and "!" (and their equivalents in other scripts) are allowed.
        if item not in settings.valid_paragraph_final and any(
                name in unicodedata.name(last, "") for name in HEADING_FORBIDDEN_FINAL):
            yield analysis.finding(end - 1, 1, WARNING, "paragraph-final", item,
                                   f"heading \\{style} ends with '{last}'")
        return
    if item in settings.invalid_paragraph_final:
        yield analysis.finding(end - 1, 1, ERROR, "paragraph-final", item,
                               f"\\{style} paragraph has a wrong ending: '{item}'")
    elif style in settings.markers_requiring_sentence_final and last not in settings.sentence_final_punctuation:
        yield analysis.finding(end - 1, 1, WARNING, "paragraph-final", item,
                               f"\\{style} paragraph should end with a sentence end mark such as a full stop ('{item}')")
    elif (
        item not in settings.valid_paragraph_final
        and not style.startswith(VERSE_LINE_STYLE_PREFIXES)
        and any(valid.split("_")[0] == style for valid in settings.valid_paragraph_final)
    ):
        yield analysis.finding(end - 1, 1, WARNING, "paragraph-final", item,
                               f"\\{style} paragraph ending is not in the allowed list: '{item}'")


def check_ordinals(analysis: Analysis, ctx: CheckContext) -> Iterator[Finding]:
    """Number + ordinal affix ("5-го", "8th", "ke-430") against NumberOrdinals / NumberOrdinalType."""
    settings = ctx.settings
    pattern = {"suffix": r"(\d+)(\D+)", "prefix": r"(\D+)(\d+)"}.get(settings.number_ordinal_type)
    if not settings.number_ordinals or not pattern:
        return
    text = analysis.segment.text
    not_after = settings.number_medial_punctuation
    for word in analysis.words:
        match = re.fullmatch(pattern, word.text)
        if not match:
            continue
        affix = match.group(2) if settings.number_ordinal_type == "suffix" else match.group(1)
        # "1Sa", "2Ki" are book abbreviations, also in scripts without capitals ("1ዜና" in \toc3); "22:43б" is a verse part.
        if affix[0].isupper() or word.text.lower() in ctx.book_name_words or (
                word.start >= 2 and text[word.start - 1] in not_after and text[word.start - 2].isdigit()):
            continue
        if affix not in settings.number_ordinals:
            yield analysis.finding(word.start, len(word.text), WARNING, "ordinals", affix,
                                   f"'{word.text}': the {settings.number_ordinal_type} '{affix}' of this number "
                                   f"is not in the Ordinal list ({places.NUMBER_SETTINGS})")


Location = tuple[str, str]  # (book, chapter:verse)


class UsageCounter:
    """Counts what occurs in the text, so list entries that never occur can be reported."""

    def __init__(self) -> None:
        self.words: Counter[str] = Counter()
        self.patterns: Counter[str] = Counter()
        self.characters: Counter[str] = Counter()
        self.abbreviations: Counter[str] = Counter()
        self.paragraph_endings: Counter[str] = Counter()  # paragraph-final items ("q2_,", "p"), headings excluded
        # Lowercase word -> (book, chapter:verse) of its first occurrence.
        self.first_seen: dict[str, tuple[str, str]] = {}
        # Lowercase word -> locations of its mid-sentence occurrences, capitalized / lowercase.
        self.case_refs: dict[str, tuple[list[Location], list[Location]]] = {}
        # (marker, lowercase word) -> locations inside / outside the character style, e.g. ("nd", "господь").
        self.style_refs: dict[tuple[str, str], tuple[list[Location], list[Location]]] = {}
        # Book -> chapter -> verse numbers present (verse ranges expanded).
        self.verses: dict[str, dict[int, set[int]]] = {}
        self.book_names: dict[str, str] = {}  # normalized \toc1-3 name or abbreviation -> book code
        self.references: list[XtReference] = []
        self.note_references: list[XtReference] = []
        # (book, chapter, verse) -> scripture text of the verse: no notes, no headings ("6-7" fills both verses).
        self.verse_texts: dict[tuple[str, int, int], str] = {}
        self.verse_ranges: set[tuple[str, int, int]] = set()  # verses written as a range (6-7): the text is shared
        # 4-digit numbers of the text (not introductions): written with / without the thousands separator,
        # each as (book, chapter:verse, number, context).
        self.four_digit: tuple[list[tuple[str, str, str, str]], list[tuple[str, str, str, str]]] = ([], [])
        self.footnotes: list[Note] = []  # footnotes of the checked books, read from the raw files
        self.poetry_lines: list[Analysis] = []  # \q, \q1, \q2 … lines of the checked books (checker/poetry.py)
        # Paragraphs and headings of the checked books in file order, notes left out (poetry checks look at neighbours).
        self.flow: list[Segment] = []
        self.segments: list[Segment] = []  # all segments of the checked books, notes too
        self.sources: list[tuple[str, str]] = []  # (book, raw file) of the checked books
        # (book, "chapter:verse") -> \nd count and words without \nd in the scripture text of the verse.
        self.nd_places: dict[tuple[str, str], VerseNd] = {}

    def _add_numbers(self, analysis: Analysis, ctx: CheckContext) -> None:
        separator = ctx.settings.number_thousands_separator
        if not separator:
            return
        text = analysis.segment.text
        for match in _numbers(text, ctx):
            start, end = match.start(), match.end()
            ref = analysis.segment.ref_at(start)
            # Introductions and front matter are full of years (1446, 2011); "H1234" is a code, not a number.
            if ref.startswith("0:") or (start and text[start - 1].isalpha()) or (end < len(text) and text[end].isalpha()):
                continue
            form = four_digit_form(match.group(), separator)
            if form is not None:
                context = analysis.finding(start, end - start, WARNING, "", "", "").context
                self.four_digit[form].append((analysis.segment.book, ref, match.group(), context))

    def _add_verse_texts(self, analysis: Analysis) -> None:
        segment = analysis.segment
        # \d (psalm title) is verse text in some versifications, so it is kept.
        if is_isolated(analysis) and segment.style != "d":
            return
        anchors = segment.anchors
        for index, (offset, chapter, verse) in enumerate(anchors):
            end = anchors[index + 1][0] if index + 1 < len(anchors) else len(segment.text)
            piece = segment.text[offset:end].strip()
            numbers = verse_range(verse)
            if not piece or not chapter.isdigit() or not numbers:
                continue
            for number in range(numbers[0], numbers[1] + 1):
                key = (segment.book, int(chapter), number)
                if numbers[0] != numbers[1]:
                    self.verse_ranges.add(key)
                self.verse_texts[key] = f"{self.verse_texts[key]} {piece}" if key in self.verse_texts else piece
        self._add_divine_name(analysis)

    def _add_divine_name(self, analysis: Analysis) -> None:
        """\\nd count and the words without \\nd of each verse of scripture text (divine-name)."""
        segment = analysis.segment
        for start, _, marker in segment.spans:
            if marker == "nd":
                self.nd_places.setdefault((segment.book, segment.ref_at(start)), VerseNd()).count += 1
        for word in analysis.words:
            # A name is not written small ("tu señor" is a man); scripts without capitals keep every word.
            if not word.text[0].islower() and "nd" not in segment.styles_at(word.start):
                place = self.nd_places.setdefault((segment.book, segment.ref_at(word.start)), VerseNd())
                place.plain.append(word.text)

    def add_source(self, book: str, content: str, ctx: CheckContext, with_references: bool = True) -> None:
        """Index a book file: its verses and names for every book, its references if it is checked."""
        if with_references:
            self.sources.append((book, content))  # raw files of the checked books (glossary, pictures, callers)
        index = index_book(book, content, ctx.settings.reference_format)
        self.verses[book] = index.verses
        for name in index.names:
            self.book_names.setdefault(_book_name_key(name), book)
        self.book_names.setdefault(_book_name_key(book), book)
        if with_references:
            self.references.extend(index.references)
            self.footnotes.extend(read_notes(book, content))
            self.note_references.extend(index.note_references)

    def _add_case_and_styles(self, analysis: Analysis, ctx: CheckContext) -> None:
        segment = analysis.segment
        text = segment.text
        # Headings and titles are often title-cased, so they say nothing about the case of a word.
        mid_sentence_possible = not is_isolated(analysis) or segment.in_note
        previous_end = None
        for word in analysis.words:
            key = word.text.lower()
            location = (segment.book, segment.ref_at(word.start))
            styled = segment.styles_at(word.start)
            # Notes quote and discuss words, often without the style they have in the text.
            for marker in STYLE_CONSISTENCY_MARKERS if not segment.in_note else ():
                inside, outside = self.style_refs.setdefault((marker, key), ([], []))
                (inside if marker in styled else outside).append(location)
            gap = text[previous_end:word.start] if previous_end is not None else None
            previous_end = word.end
            if (
                gap is None or not mid_sentence_possible or not word.text[0].isalpha() or word.text.isupper()
                or any(ch in ctx.sentence_starters for ch in gap)
            ):
                continue
            capitalized, lowercase = self.case_refs.setdefault(key, ([], []))
            (capitalized if word.text[0].isupper() else lowercase).append(location)

    def add(self, analysis: Analysis, ctx: CheckContext | None = None) -> None:
        segment = analysis.segment
        text = segment.text
        runs = analysis.runs
        self.words.update(word.text for word in analysis.words)
        for word in analysis.words:
            key = word.text.lower()
            if key not in self.first_seen:
                self.first_seen[key] = (segment.book, segment.ref_at(word.start))
        if ctx:
            self._add_case_and_styles(analysis, ctx)
            self._add_numbers(analysis, ctx)
            ending = paragraph_ending(segment, ctx)
            if ending and not HEADING_STYLE_RE.match(segment.style):
                self.paragraph_endings[ending[0]] += 1
        self._add_verse_texts(analysis)
        if is_poetry_line(analysis):
            self.poetry_lines.append(analysis)
        if not segment.in_note:
            self.flow.append(segment)
        self.segments.append(segment)
        self.characters.update(cluster for _, cluster in graphemes(text))
        for index, run in enumerate(runs):
            if run.is_word:
                if index + 1 < len(runs) and runs[index + 1].text.startswith("."):
                    self.abbreviations[f"{run.text}.".lower()] += 1
            elif not run.text.isspace() and not (ctx and is_number_separator(runs, index, ctx)):
                self.patterns[punctuation_pattern(run, len(text))] += 1


def _unused(source: str, list_name: str, entries: Iterable[str], counts: Counter[str]) -> Iterator[Finding]:
    for entry in sorted(entries):
        if not counts[entry]:
            yield Finding(book=source, ref=list_name, severity=WARNING, check="unused", item=entry,
                          message=f"'{entry}' is in the list but never used in the text", context="")


_STATE_NAMES = {STATE_RIGHT: "(right, R)", STATE_WRONG: "(wrong, W)"}


def check_unused(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    """Entries of Settings.xml lists and SpellingStatus.xml that never occur in the checked books."""
    settings = ctx.settings
    single_graphemes = {item for item in settings.valid_characters if len(list(graphemes(item))) == 1}
    yield from _unused(places.CHARACTERS, places.CORRECT, single_graphemes, usage.characters)
    yield from _unused(places.PUNCTUATION, places.CORRECT, settings.valid_punctuation, usage.patterns)
    yield from _unused("Settings.xml", "Abbreviations", ctx.abbreviations, usage.abbreviations)
    yield from _unused(places.MIXED_CAPITALIZATION, places.WRONG, settings.invalid_mixed_capitalization,
                       usage.words)

    spelling_counts: Counter[str] = Counter()
    for word, count in usage.words.items():
        entry = ctx.spelling.lookup(word)
        if entry:
            spelling_counts[entry.word] += count
    for state in sorted({entry.state for entry in ctx.spelling.entries.values()}):
        entries = [key for key, entry in ctx.spelling.entries.items() if entry.state == state]
        yield from _unused(places.WORDLIST, _STATE_NAMES.get(state, f"(state {state})"), entries, spelling_counts)

    if ctx.hyphenation:
        lowercase_counts = Counter()
        for word, count in usage.words.items():
            lowercase_counts[word.lower()] += count
        yield from _unused(HYPHENATION_FILE, "words", (e.word.lower() for e in ctx.hyphenation.words),
                           lowercase_counts)


def _list_finding(ref: str, severity: str, check: str, item: str, message: str) -> Finding:
    return Finding(book=HYPHENATION_FILE, ref=ref, severity=severity, check=check, item=item,
                   message=message, context="")


def check_hyphenation(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    """Rules, consistency and coverage of hyphenatedWords.txt."""
    if not ctx.hyphenation:
        return
    hyphenation = ctx.hyphenation
    entries = hyphenation.words
    text_words = {word.lower() for word in usage.words}
    no_break_before = ctx.settings.word_medial_punctuation - {hyphenation.hard_hyphen}
    for entry in entries:
        ref = f"line {entry.line}"
        for problem in rule_violations(entry, ctx.language, no_break_before):
            yield _list_finding(ref, ERROR, "hyphenation", entry.text, f"'{entry.text}': {problem}")
        if is_unhyphenated(entry, ctx.language, hyphenation.hard_hyphen) and entry.word.lower() in text_words:
            yield _list_finding(ref, WARNING, "hyphenation", entry.text, f"'{entry.text}' is a long word with no places to break it")

    # Unreviewed entries (no "*"): listed one by one only when there are few of them;
    # in a mostly generated list a single summary line is more useful.
    unreviewed = [entry for entry in entries if not entry.locked]
    if len(unreviewed) > MAX_LISTED_UNREVIEWED:
        yield _list_finding("summary", WARNING, "hyphenation", "unreviewed",
                            f"{len(unreviewed)} of {len(entries)} entries are not checked by a person (no '*' at the start)")
    else:
        for entry in unreviewed:
            yield _list_finding(f"line {entry.line}", WARNING, "hyphenation", entry.text,
                                f"'{entry.text}' is not checked by a person (no '*' at the start)")

    for issue in inconsistent_affixes(entries):
        shown = f"{issue.affix}-" if issue.side == "prefix" else f"-{issue.affix}"
        yield _list_finding(
            f"line {issue.entry.line}", WARNING, "hyphenation", issue.entry.text,
            f"'{issue.entry.text}' breaks the {issue.side} '{shown}' as '{issue.actual}', but "
            f"{issue.majority_count} of {issue.group_count} words break it as '{issue.expected}' "
            f"(for example {issue.example})")

    known = ctx.hyphenation.by_word
    missing = Counter()
    for word, count in usage.words.items():
        if word.lower() not in known and not any(ch.isdigit() for ch in word):
            missing[word.lower()] += count
    for word, count in sorted(missing.items()):
        yield _list_finding("missing", WARNING, "hyphenation", word,
                            f"'{word}' is used {count} times in the text but is not in the list")


def check_variants(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    """Rare capitalized words one edit away from a frequent one: "Петор" (1×) vs "Петро" (141×).

    Only words that never occur in lowercase (names); in scripts without capitals every word.
    Differences in the last letters are skipped, they are usually inflection ("Ізраїле" / "Ізраїля").
    """
    counts: Counter[str] = Counter()
    lowercase_seen: set[str] = set()
    for word, count in usage.words.items():
        counts[word.lower()] += count
        # Scripts without capitals have no lowercase either: every word can be a name there.
        if word[0].islower():
            lowercase_seen.add(word.lower())
    names = [word for word in counts
             if word not in lowercase_seen and len(word) >= VARIANT_MIN_LENGTH and not any(ch.isdigit() for ch in word)]
    # Words sharing a one-letter deletion are candidates for a single edit.
    by_deletion: dict[str, list[str]] = {}
    for word in names:
        for key in {word, *(word[:i] + word[i + 1:] for i in range(len(word)))}:
            by_deletion.setdefault(key, []).append(word)
    reported: set[tuple[str, str]] = set()
    for group in by_deletion.values():
        for rare in group:
            if counts[rare] > VARIANT_MAX_RARE:
                continue
            for frequent in group:
                if (rare, frequent) in reported or counts[frequent] < VARIANT_MIN_RATIO * counts[rare]:
                    continue
                edit = single_edit(rare, frequent)
                if not edit or (edit[0] != "transposition"
                                and edit[1] >= min(len(rare), len(frequent)) - VARIANT_IGNORED_ENDING):
                    continue
                # Without capitals every word is a candidate, so a different first letter is mostly a prefix.
                if edit[1] == 0 and rare[0].upper() == rare[0]:
                    continue
                reported.add((rare, frequent))
                entry = ctx.spelling.lookup(rare)
                approved = f" (approved in {places.WORDLIST})" if entry and entry.state == STATE_RIGHT else ""
                book, ref = usage.first_seen.get(rare, ("", ""))
                yield Finding(book=book, ref=ref, severity=WARNING, check="variants", item=rare,
                              message=f"'{rare}' ({counts[rare]}×){approved} looks like another spelling of "
                                      f"'{frequent}' ({counts[frequent]}×): {EDIT_NAMES[edit[0]]}", context="")


def _minority(first: list[Location], second: list[Location]) -> int:
    """0 if `first` is a rare minority, 1 if `second` is, -1 if neither (or the word is too rare)."""
    total = len(first) + len(second)
    if total < CONSISTENCY_MIN_OCCURRENCES or not first or not second:
        return -1
    if len(first) <= CONSISTENCY_MINORITY_SHARE * total:
        return 0
    if len(second) <= CONSISTENCY_MINORITY_SHARE * total:
        return 1
    return -1


def check_name_case(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    """A word nearly always capitalized mid-sentence but sometimes not ("господь" vs 95× "Господь"),
    or the other way round. Sentence starts and headings are not counted."""
    forms: dict[str, Counter[str]] = {}
    for word, count in usage.words.items():
        forms.setdefault(word.lower(), Counter())[word] += count
    for key, (capitalized, lowercase) in sorted(usage.case_refs.items()):
        side = _minority(capitalized, lowercase)
        if side < 0:
            continue
        minority, majority = (capitalized, lowercase) if side == 0 else (lowercase, capitalized)
        upper_first = side == 1  # the majority is capitalized
        usual = next((w for w, _ in forms[key].most_common() if w[0].isupper() == upper_first), key)
        rare = next((w for w, _ in forms[key].most_common() if w[0].isupper() != upper_first), key)
        for book, ref in minority:
            yield Finding(book, ref, WARNING, "name-case", key,
                          f"'{rare}' in the middle of a sentence, usually written '{usual}' ({len(majority)} of "
                          f"{len(majority) + len(minority)})", "")


MIN_USUAL_NUMBERS = 10  # the usual way of writing 4-digit numbers is used at least this often
MAX_RARE_SHARE = 0.1  # and the other way in at most this part of the 4-digit numbers


def check_numbers(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    """4-digit numbers written in the rare way of the project: "4000" where 118 others are "4.000", or the reverse.
    Settings.xml does not say how 4-digit numbers are written, so the text decides."""
    plain, separated = usage.four_digit
    total = len(plain) + len(separated)
    if not total:
        return
    for rare, usual, has_separator in ((plain, separated, False), (separated, plain, True)):
        if not rare or len(usual) < MIN_USUAL_NUMBERS or len(rare) > total * MAX_RARE_SHARE:
            continue
        shown = _separator_text(ctx.settings.number_thousands_separator)
        example = Counter(number for _, _, number, _ in usual).most_common(1)[0][0]
        for book, ref, number, context in rare:
            how = "has the thousands separator" if has_separator else f"has no thousands separator {shown}"
            yield Finding(book, ref, WARNING, "numbers", number,
                          f"number '{number}' {how}, but {len(usual)} of {total} numbers with 4 digits are "
                          f"written like '{example}'. Is it a year?", context)


def check_footnote_forms(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    """Footnotes built differently from similar ones (checker/footnotes.py)."""
    yield from check_footnotes(usage.footnotes, frozenset(ctx.settings.sentence_final_punctuation), usage.verse_texts)


def check_styled_words(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    """A word nearly always inside a character style (\\nd) but sometimes not, or the other way round."""
    for (marker, key), (inside, outside) in sorted(usage.style_refs.items()):
        side = _minority(inside, outside)
        if side < 0:
            continue
        minority, majority = (inside, outside) if side == 0 else (outside, inside)
        where = f"in \\{marker}" if side == 0 else f"without \\{marker}"
        usual = f"without \\{marker}" if side == 0 else f"in \\{marker}"
        for book, ref in minority:
            yield Finding(book, ref, WARNING, "styled-words", key,
                          f"'{key}' {where}, usually {usual} ({len(majority)} of "
                          f"{len(majority) + len(minority)})", "")


def check_divine_name_verses(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    """The divine name without \\nd in a verse where translations have it in \\nd (checker/divine_name.py)."""
    if ctx.to_original is None:
        ctx.skipped["divine-name"] = (f"Not checked: the versification of the project "
                                      f"({ctx.settings.versification}) is not a standard one.")
        return
    if not usual_nd_words(usage.style_refs):
        ctx.skipped["divine-name"] = ("Not checked: no word of the project is nearly always in \\nd (the divine name "
                                      "is not marked with \\nd, or too seldom).")
        return
    yield from check_divine_name(usage.style_refs, usage.nd_places, usage.verse_texts, ctx.to_original)


def _book_name_key(name: str) -> str:
    # "~" is the USFM no-break space: "\toc3 1~Цар." = "1 Цар.".
    return " ".join(name.replace("~", " ").lower().rstrip(".").split())


def _name_to_book(name: str, usage: UsageCounter, ctx: CheckContext) -> str | None:
    """Book code of a name as written; "" if the name is only abbreviations ("див."); None if unknown."""
    # Leading words are dropped one by one until the rest is a book name: "див. Мт." -> "Мт.", "см. также Пс." ->
    # "Пс.". A book abbreviation may also be listed in Abbreviations ("Євр.", "См. Исх."), so the rest is tried
    # after each step. Only abbreviations ("див.") = no name; other words without a book = unknown name.
    words = name.split()
    only_abbreviations = all(word.lower() in ctx.abbreviations for word in words)
    while words:
        key = _book_name_key(" ".join(words))
        if key in usage.book_names:
            return usage.book_names[key]
        words.pop(0)
    return "" if only_abbreviations else None


def _part_targets(part: ReferencePart, book: str) -> Iterator[tuple[str, int, int, int]]:
    for first, last in part.verses:
        yield book, part.chapter, first, last
    if part.end:
        yield book, part.end[0], part.end[1], part.end[1]


def _reference_targets(reference: XtReference, usage: UsageCounter, ctx: CheckContext
                       ) -> Iterator[tuple[str, int, int, int] | str]:
    """(book, chapter, first verse, last verse) per verse span in an \\xt, or an unknown book name.

    "Бут. 1:1, 3; 2:3" -> GEN 1:1, GEN 1:3, GEN 2:3 (a part without a name keeps the previous book);
    "8-му|GEN 2:8" -> the link attribute is used. Parts without chapter and verse are skipped.
    """
    text, _, link = reference.text.partition("|")
    if link:
        if book_match := LINK_BOOK_RE.search(link):
            for part in parse_reference(link[book_match.start():], LINK_FORMAT)[0]:
                yield from _part_targets(part, book_match.group(1))
        return
    # In front/back matter and notes books (introductions to many books) a reference without a book name does not
    # point into that book itself: such parts are skipped until a name is given.
    book: str | None = None if reference.book in PERIPHERAL_BOOKS else reference.book
    for part in parse_reference(text, ctx.settings.reference_format)[0]:
        if part.name:
            found = _name_to_book(part.name, usage, ctx)
            if found is None:
                # The parts after an unknown name belong to that unknown book.
                book = None
                yield part.name
                continue
            book = found or book
        if book:
            yield from _part_targets(part, book)


def _link_problems(reference: XtReference) -> Iterator[tuple[str, str]]:
    """(item, message) when the text of an \\xt and its link attribute do not agree: "8|JER 22:28"."""
    text, _, link = reference.text.partition("|")
    book_match = LINK_BOOK_RE.search(link)
    if not book_match:
        return
    target = link[book_match.start():].strip()
    for letter in (ch for ch in target if ch.isalpha() and not ch.isascii()):
        yield letter, f"the link {target} has the letter '{letter}'; a link has only a book code and numbers"
    linked: set[int] = set()
    for part in parse_reference(target, LINK_FORMAT)[0]:
        linked.add(part.chapter)
        linked.update(verse for first, last in part.verses for verse in range(first, last + 1))
    # A book number in the text is not a chapter or verse: "1 Сам. 3:4".
    numbers = {int(number) for number in re.findall(r"\d+", BOOK_NAME_BEFORE_NUMBER_RE.sub(" ", text))}
    if linked and numbers - linked:
        yield target, f"the text '{text.strip()}' and the link {target} show different numbers"


def check_references(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    """References must exist and use the marks of Settings.xml (book names from \\toc1-3)."""
    fmt = ctx.settings.reference_format
    for reference in usage.references:
        def finding(severity: str, item: str, message: str) -> Finding:
            return Finding(reference.book, reference.ref, severity, "references", item,
                           f"{message} in \\{reference.marker} '{reference.text}'", reference.context)
        for issue in parse_reference(reference.text.partition("|")[0], fmt)[1]:
            yield finding(WARNING if issue.is_question else ERROR, issue.item, issue.message)
        for item, message in _link_problems(reference):
            yield finding(WARNING, item, message)
        for target in _reference_targets(reference, usage, ctx):
            if isinstance(target, str):
                yield finding(WARNING, target, f"book name '{target}' is not in {places.BOOK_NAMES} (\\toc1-3)")
                continue
            book, chapter, first, last = target
            verses = usage.verses.get(book)
            shown = f"{book} {chapter}{fmt.chapter_verse}{first}" + (f"-{last}" if last != first else "")
            if verses is None:
                yield finding(WARNING, book, f"{shown}: this book is not in the project")
            elif chapter not in verses:
                yield finding(ERROR, shown, f"{shown}: chapter {chapter} does not exist")
            # Verse 0 is the chapter's title or introduction ("Пс. 8:0", "ACT 1:0").
            elif missing := [v for v in range(first, last + 1) if v and v not in verses[chapter]]:
                yield finding(ERROR, shown, f"{shown}: verse {_compact(missing)} does not exist")
    for reference in usage.note_references:
        for issue in parse_reference(reference.text, fmt)[1]:
            yield Finding(reference.book, reference.ref, WARNING if issue.is_question else ERROR, "references",
                          issue.item, f"{issue.message} in \\{reference.marker} '{reference.text}'", reference.context)


def _verse_of(ref: str) -> tuple[int, int] | None:
    """"5:3" or "5:3-4" -> (5, 3); None for other places."""
    match = re.match(r"(\d+):(\d+)", ref)
    return (int(match.group(1)), int(match.group(2))) if match else None


def check_self_references(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    """A cross reference (\\x) that points to the verse it stands in. Footnotes may name their own verse
    ("some manuscripts do not have verse 28"), so only \\x notes are checked."""
    for reference in usage.references:
        if reference.note not in ("x", "ex"):
            continue
        origin = _verse_of(reference.ref)
        if not origin or origin[1] == 0:
            continue
        for target in _reference_targets(reference, usage, ctx):
            if isinstance(target, str):
                continue
            book, chapter, first, last = target
            if book == reference.book and chapter == origin[0] and first <= origin[1] <= last:
                yield Finding(reference.book, reference.ref, WARNING, "self-references", reference.text,
                              f"the cross reference '{reference.text}' points to the verse it stands in", reference.context)
                break


MIN_ONE_CHAPTER = 3  # references to one-chapter books needed to know the usual form


def check_one_chapter_books(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    """References to books with one chapter written two ways: "Jude 1:3" and "Jude 3". The rare way is listed."""
    one_chapter = {book for book, chapters in usage.verses.items()
                   if set(chapters) == {1} and book not in PERIPHERAL_BOOKS}
    names = sorted((name for name, book in usage.book_names.items() if book in one_chapter and any(
        ch.isalpha() for ch in name)), key=len, reverse=True)
    if not names:
        return
    mark = re.escape(ctx.settings.reference_format.chapter_verse or ":")
    name_re = "|".join(r"\s+".join(re.escape(word) for word in name.split()) for name in names)
    pattern = re.compile(rf"(?<!\w)({name_re})\.?[\s ~]*(\d+)(?:{mark}(\d+))?(?!\d)", re.IGNORECASE)
    places = []
    for reference in usage.references:
        for match in pattern.finditer(reference.text.partition("|")[0]):
            places.append((reference, match, match.group(3) is not None))
    with_chapter = sum(1 for _, _, has in places if has)
    without = len(places) - with_chapter
    if len(places) < MIN_ONE_CHAPTER or min(with_chapter, without) == 0:
        return
    rare = with_chapter <= without
    if min(with_chapter, without) * 2 > max(with_chapter, without):
        return  # no clear usual way
    usual = max(with_chapter, without)
    for reference, match, has in places:
        if has != rare:
            continue
        text = match.group()
        number_at = match.start(2) - match.start()
        better = (text[:number_at] + match.group(3) if has
                  else f"{text[:number_at]}1{ctx.settings.reference_format.chapter_verse}{match.group(2)}")
        how = "without the chapter" if has else "with the chapter"
        yield Finding(reference.book, reference.ref, WARNING, "one-chapter-books", match.group(),
                      f"'{match.group()}': {usual} of {len(places)} references to books with one chapter are written "
                      f"{how}: write '{better}'", reference.context)


def _name_as_written(name: str, usage: UsageCounter) -> tuple[str, str] | None:
    """(the book name as written, book code): leading words such as "see" are dropped like in _name_to_book."""
    words = name.split()
    while words:
        written = " ".join(words)
        if (key := _book_name_key(written)) in usage.book_names:
            return written, usage.book_names[key]
        words.pop(0)
    return None


MIN_USUAL_NAME = 20  # the usual name of a book in references is used at least this often
NAME_RATIO = 10  # and at least this many times more than the rare one


def check_book_name_forms(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    """One book named two ways in \\xt references ("Lk 3:23" 1345 times, "Luk 3:23" twice): the rare name is listed.
    Each name may be in \\toc1-3; the project should use one."""
    fmt = ctx.settings.reference_format
    places: dict[str, list[tuple[XtReference, str]]] = {}
    for reference in usage.references:
        if reference.marker != "xt" or reference.book in PERIPHERAL_BOOKS:
            continue
        for part in parse_reference(reference.text.partition("|")[0], fmt)[0]:
            if part.name and (found := _name_as_written(part.name, usage)):
                places.setdefault(found[1], []).append((reference, found[0]))
    for book, items in places.items():
        counts = Counter(name for _, name in items)
        if len(counts) < 2:
            continue
        usual, usual_count = counts.most_common(1)[0]
        if usual_count < MIN_USUAL_NAME:
            continue
        for reference, name in items:
            # "Psalm" / "Psalms": one name in two grammatical forms, not two names.
            same_name = name.startswith(usual) or usual.startswith(name)
            if name != usual and not same_name and usual_count >= counts[name] * NAME_RATIO:
                yield Finding(reference.book, reference.ref, WARNING, "book-name-forms", name,
                              f"'{name}': {usual_count} of {len(items)} references to {book} write '{usual}'",
                              reference.context)


def _compact(numbers: list[int]) -> str:
    return f"{numbers[0]}-{numbers[-1]}" if len(numbers) > 1 else str(numbers[0])


def _spelling_finding(severity: str, item: str, message: str) -> Finding:
    return Finding(book=places.WORDLIST, ref="Spelling", severity=severity, check="lists", item=item,
                   message=message, context="")


def check_lists(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    """Contradictions inside SpellingStatus.xml and between it, Settings.xml and hyphenatedWords.txt."""
    entries = ctx.spelling.entries
    for key, entry in sorted(entries.items()):
        lowercase = entries.get(key.lower())
        if key != key.lower() and lowercase and lowercase.state != entry.state:
            yield _spelling_finding(WARNING, key, f"'{key}' is {entry.state} but '{lowercase.word}' is "
                                                  f"{lowercase.state}")
        for case in entry.specific_cases:
            if case.lower() != key.lower():
                yield _spelling_finding(WARNING, key, f"'{key}' is written '{case}' in {places.WORDLIST}, which has different letters")
        if entry.state == STATE_RIGHT and entry.corrections:
            yield _spelling_finding(WARNING, key, f"'{key}' is approved but has a correction "
                                                  f"'{', '.join(entry.corrections)}'")
        for correction in entry.corrections:
            target = ctx.spelling.lookup(correction)
            if target and target.state == STATE_WRONG:
                yield _spelling_finding(ERROR, key, f"the correction '{correction}' of '{key}' is also marked as wrong (W)")
        if entry.state == STATE_WRONG and key.lower() in ctx.book_title_words:
            yield _spelling_finding(WARNING, key, f"'{key}' is marked wrong (W), but it is a word of a book name "
                                                  f"(\\toc1-3): change the {places.WORDLIST} or the book name")
    for word in sorted(ctx.settings.invalid_mixed_capitalization):
        entry = ctx.spelling.lookup(word)
        if entry and entry.state == STATE_RIGHT and word in (entry.word, *entry.specific_cases):
            yield Finding(places.MIXED_CAPITALIZATION, places.WRONG, WARNING, "lists", word,
                          f"'{word}' is marked wrong in {places.MIXED_CAPITALIZATION} but is approved in "
                          f"{places.WORDLIST}", "")
    if ctx.hyphenation:
        for entry in ctx.hyphenation.words:
            # An entry without letters ("-", which Publishing Assistant puts into every list) is not a word.
            if not any(ch.isalpha() for ch in entry.word):
                continue
            spelling = ctx.spelling.lookup(entry.word)
            if spelling and spelling.state == STATE_WRONG:
                yield _list_finding(f"line {entry.line}", WARNING, "lists", entry.text,
                                    f"'{entry.text}' is hyphenated, but '{spelling.word}' is marked wrong (W) in "
                                    f"{places.WORDLIST}")


CHECKS: dict[str, Callable[[Analysis, CheckContext], Iterator[Finding]]] = {
    "characters": check_characters,
    "punctuation": check_punctuation,
    "mixed-capitalization": check_mixed_capitalization,
    "capitalization": check_capitalization,
    "spelling": check_spelling,
    "repeated-words": check_repeated_words,
    "spacing": check_spacing,
    "scripts": check_scripts,
    "normalization": check_normalization,
    "paragraph-final": check_paragraph_final,
    "ordinals": check_ordinals,
}
# Checks that need all segments of a book in order (e.g. a quote may span paragraphs).
BOOK_CHECKS: dict[str, Callable[[list[Analysis], CheckContext], Iterator[Finding]]] = {
    "quotes": check_quotes,
    "pairs": check_pairs,
}
def check_usfm(book: str, content: str, ctx: CheckContext, file_name: str = "") -> Iterator[Finding]:
    if file_name:
        settings = ctx.settings
        name_book = book_from_file_name(
            file_name, settings.file_name_pre_part, settings.file_name_post_part, settings.file_name_book_form)
        yield from check_file(book, content, file_name, name_book)
    counts = ctx.verse_counts.get(book) if ctx.verse_counts else None
    english = ctx.english_counts.get(book, {}) if ctx.english_counts is not None else None
    yield from check_structure(book, content, ctx.settings.reference_format, counts, english)


# Checks of the raw USFM file (markers, chapter and verse numbers): (book code, file content, ctx, file name).
SOURCE_CHECKS: dict[str, Callable[..., Iterator[Finding]]] = {
    "usfm": check_usfm,
    "book-titles": lambda book, content, ctx, file_name="": check_book_titles(
        book, content, ctx.book_number_forms),
    "special-spaces": lambda book, content, ctx, file_name="": check_special_spaces(book, content, ctx),
}
# Checks that run once after all books were read.
PROJECT_CHECKS: dict[str, Callable[[UsageCounter, CheckContext], Iterator[Finding]]] = {
    "unused": check_unused,
    "hyphenation": check_hyphenation,
    "lists": check_lists,
    "approvals": check_approvals,
    "variants": check_variants,
    "name-case": check_name_case,
    "styled-words": check_styled_words,
    "divine-name": check_divine_name_verses,
    "numbers": check_numbers,
    "footnotes": check_footnote_forms,
    "footnote-quotes": lambda usage, ctx: check_footnote_quotes(usage.footnotes, usage.verse_texts),
    "references": check_references,
    "parallel-changes": check_parallel_changes,
    "parallel-differences": check_parallel_differences,
    "terms": check_terms,
    "term-lists": check_term_lists,
    "term-renderings": check_term_renderings,
    "poetry-numbers": lambda usage, ctx: check_poetry_numbers(usage.poetry_lines, ctx),
    "self-references": check_self_references,
    "one-chapter-books": check_one_chapter_books,
    "repeated-text": lambda usage, ctx: check_repeated_text(usage.verse_texts, usage.verse_ranges),
    "verse-lengths": lambda usage, ctx: check_verse_lengths(usage.verse_texts, usage.verse_ranges,
                                                            ctx.to_original, ctx),
    "glossary-words": lambda usage, ctx: check_glossary_words(usage.sources, ctx),
    "figures": lambda usage, ctx: check_figures(usage.sources, ctx.project, ctx),
    "dashes": lambda usage, ctx: check_dashes(usage.segments, ctx),
    "ellipses": lambda usage, ctx: check_ellipses(usage.segments, ctx),
    "all-caps": lambda usage, ctx: check_all_caps(usage.segments, ctx),
    "marker-capitals": lambda usage, ctx: check_marker_capitals(usage.segments, ctx),
    "heading-case": lambda usage, ctx: check_heading_case(usage.flow, usage.case_refs, ctx),
    "note-callers": lambda usage, ctx: check_note_callers(usage.sources, ctx),
    "book-name-forms": check_book_name_forms,
    "untranslated-verses": lambda usage, ctx: check_untranslated(usage.verse_texts, usage.words, ctx),
    "apostrophes": lambda usage, ctx: check_apostrophes(usage.segments, ctx),
    "digit-systems": lambda usage, ctx: check_digit_systems(usage.segments, ctx),
    "fractions": lambda usage, ctx: check_fractions(usage.segments, ctx),
    "line-ends": lambda usage, ctx: check_line_ends(usage.flow, usage.case_refs, ctx),
    "poetry-two-sentences": lambda usage, ctx: check_poetry_two_sentences(usage.poetry_lines, ctx),
    "poetry-long-lines": lambda usage, ctx: check_poetry_long_lines(usage.poetry_lines, ctx),
    "poetry-verse-inside": lambda usage, ctx: check_poetry_verse_inside(usage.poetry_lines, ctx),
    "poetry-chapter-break": lambda usage, ctx: check_poetry_chapter_break(usage.flow, ctx),
}
# Checks that need the Biblical Terms files (read only when one of them runs).
TERM_CHECKS = frozenset({"terms", "term-lists", "term-renderings"})
