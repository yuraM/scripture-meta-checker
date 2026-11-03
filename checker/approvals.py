"""approvals: list entries that a person approved (or rejected) in Paratext, but that look wrong.

Some people approve whole lists without looking. Such approvals cannot be dated (the files have no history),
but some approved entries are wrong by themselves, and some rejected ones are used so often that the mark
itself is probably the mistake. All rules use Unicode properties, never letters of a language.
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Iterator
from typing import TYPE_CHECKING

from checker import places
from checker.hyphenation import rule_violations, word_scripts
from checker.model import WARNING, CheckContext, Finding
from checker.spelling import STATE_RIGHT

if TYPE_CHECKING:
    from checker.checks import UsageCounter

CHECK = "approvals"
# Characters that have no place in Scripture text, by Unicode category.
SPECIAL_CHARACTERS = {
    "Co": "a private use character: it has no standard look, other fonts show a box",
    "Cc": "a control character",
    "Cn": "not a Unicode character",
    "Cs": "half of a broken character (surrogate)",
}
# Signs that normally have no space before them and are not written twice, by Unicode name
# (so "፣" ETHIOPIC COMMA or "।" DEVANAGARI DANDA count too).
SPACE_BEFORE_NAMES = ("COMMA", "FULL STOP", "SEMICOLON", "COLON", "QUESTION MARK", "EXCLAMATION MARK", "DANDA")
# A rejected item is probably marked by mistake if it is used at least this often
# (a paragraph ending also in at least this share of all paragraphs of its marker: 1742 of 12433 "\q2").
MIN_REJECTED_USES = 20
MIN_REJECTED_SHARE = 0.1
# A list is "all approved" from this share and size on.
ALL_APPROVED_SHARE = 0.99
ALL_APPROVED_MIN_ENTRIES = 100
# The text uses capital letters if at least this share of its letters are capitals.
CASED_MIN_SHARE = 0.01
EXAMPLES = 3  # example words in one finding


def _finding(place: str, status: str, item: str, message: str) -> Finding:
    return Finding(book=place, ref=status, severity=WARNING, check=CHECK, item=item, message=message, context="")


def _is_stop_mark(ch: str) -> bool:
    name = unicodedata.name(ch, "")
    return unicodedata.category(ch).startswith("P") and any(part in name for part in SPACE_BEFORE_NAMES)


def _words(count: int) -> str:
    return "1 word" if count == 1 else f"{count} words"


def _times(count: int) -> str:
    return "never used in the text" if not count else f"used {count} times" if count > 1 else "used once"


def suspicious_punctuation(pattern: str) -> str:
    """Why an approved punctuation pattern looks wrong ("" if it does not): "_," or ",,"."""
    for index, ch in enumerate(pattern):
        if not _is_stop_mark(ch):
            continue
        before = pattern[index - 1] if index else ""
        after = pattern[index + 1] if index + 1 < len(pattern) else ""
        # "..." / "!!!" are a deliberate run of marks, two equal marks are a typing slip.
        if after == ch and before != ch and pattern[index + 2:index + 3] != ch:
            return f"'{ch}' is written two times"
        if before == "_" and after != ch:
            return f"it has a space before '{ch}'"
    return ""


def _characters(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    for item in sorted(ctx.settings.valid_characters):
        reasons = [SPECIAL_CHARACTERS[unicodedata.category(ch)] for ch in item
                   if unicodedata.category(ch) in SPECIAL_CHARACTERS]
        if reasons:
            codes = " ".join(f"U+{ord(ch):04X}" for ch in item)
            yield _finding(places.CHARACTERS, places.CORRECT, item,
                           f"'{item}' ({codes}) is marked correct in {places.CHARACTERS}, but it is {reasons[0]} "
                           f"({_times(usage.characters[item])})")


def _punctuation(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    for pattern in sorted(ctx.settings.valid_punctuation):
        # Not used any more: the text was corrected, the old mark does no harm.
        if usage.patterns[pattern] and (reason := suspicious_punctuation(pattern)):
            yield _finding(places.PUNCTUATION, places.CORRECT, pattern,
                           f"'{pattern}' is marked correct in {places.PUNCTUATION}, but {reason} "
                           f"({_times(usage.patterns[pattern])})")


def _rejected_but_used(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    settings = ctx.settings
    for item in sorted(settings.invalid_paragraph_final):
        count = usage.paragraph_endings[item]
        style = item.split("_")[0]
        total = sum(n for other, n in usage.paragraph_endings.items() if other.split("_")[0] == style)
        if count >= MIN_REJECTED_USES and count >= MIN_REJECTED_SHARE * total:
            yield _finding(places.FINAL_PUNCTUATION, places.WRONG, item,
                           f"'{item}' is marked wrong in {places.FINAL_PUNCTUATION}, but {count} of {total} "
                           f"\\{style} paragraphs end like this: maybe the mark is a mistake")
    for place, items, counts in ((places.PUNCTUATION, settings.invalid_punctuation, usage.patterns),
                                 (places.CHARACTERS, settings.invalid_characters, usage.characters)):
        for item in sorted(items):
            if counts[item] >= MIN_REJECTED_USES:
                yield _finding(place, places.WRONG, item, f"'{item}' is marked wrong in {place}, but it is "
                                                          f"used {counts[item]} times: maybe the mark is a mistake")


def _has_case(usage: UsageCounter) -> bool:
    """The text uses capital letters at all (Ethiopic and Devanagari do not)."""
    letters: Counter[str] = Counter()
    for cluster, count in usage.characters.items():
        letters[unicodedata.category(cluster[0])] += count
    total = sum(letters[category] for category in ("Lu", "Ll", "Lt", "Lo"))
    return total > 0 and letters["Lu"] + letters["Lt"] >= CASED_MIN_SHARE * total


def _switched_off(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    settings = ctx.settings
    bare = sorted(item for item in settings.valid_sentence_final_capitalization
                  if item in settings.sentence_final_punctuation)
    if bare and _has_case(usage):
        marks = " ".join(bare)
        yield _finding(places.PUNCTUATION_LOWERCASE, places.CORRECT, marks,
                       f"'{marks}' alone are marked correct in {places.PUNCTUATION_LOWERCASE}: then the "
                       f"capitalization check never reports a small letter after these marks and a space")
    if settings.normalization_form not in ("NFC", "NFD", "NFKC", "NFKD"):
        yield _finding("Settings.xml", "NormalizationForm", "NormalizationForm",
                       "Settings.xml has no NormalizationForm: the normalization check does nothing")


def _wordlist(ctx: CheckContext) -> Iterator[Finding]:
    rejected = ctx.settings.invalid_characters
    with_rejected: dict[str, list[str]] = {}
    for _, entry in sorted(ctx.spelling.entries.items()):
        if entry.state != STATE_RIGHT:
            continue
        for word in dict.fromkeys((entry.word, *entry.specific_cases)):
            for ch in sorted({ch for ch in word if ch in rejected}):
                with_rejected.setdefault(ch, []).append(word)
            # Phrases with spaces may name a letter of another alphabet on purpose (Psalm 119 headings).
            if any(ch.isspace() for ch in word):
                continue
            special = [ch for ch in word if unicodedata.category(ch) in SPECIAL_CHARACTERS]
            scripts = word_scripts(word)
            if len(scripts) > 1:
                reason = f"has letters from different alphabets: {' + '.join(sorted(scripts))}"
            elif special:
                reason = f"has {SPECIAL_CHARACTERS[unicodedata.category(special[0])]} U+{ord(special[0]):04X}"
            else:
                continue
            yield _finding(places.WORDLIST, "(right, R)", word,
                           f"'{word}' is marked right in {places.WORDLIST}, but it {reason}")
            break  # one line per entry, not one per capitalized form
    # One line per character: many such words usually mean that the character mark is the mistake.
    for ch, words in sorted(with_rejected.items()):
        yield _finding(places.CHARACTERS, places.WRONG, ch,
                       f"'{ch}' (U+{ord(ch):04X}) is marked wrong in {places.CHARACTERS}, but {_words(len(words))} "
                       f"with it {'is' if len(words) == 1 else 'are'} marked right in {places.WORDLIST} (for example "
                       f"{', '.join(words[:EXAMPLES])})")


def _hyphenation(ctx: CheckContext) -> Iterator[Finding]:
    from checker.checks import HYPHENATION_FILE

    hyphenation = ctx.hyphenation
    if not hyphenation:
        return
    no_break_before = ctx.settings.word_medial_punctuation - {hyphenation.hard_hyphen}
    for entry in hyphenation.words:
        if entry.locked and (problems := list(rule_violations(entry, ctx.language, no_break_before))):
            yield Finding(HYPHENATION_FILE, f"line {entry.line}", WARNING, CHECK, entry.text,
                          f"'{entry.text}' is marked checked by a person (*), but: {problems[0]}", "")


def _all_approved(ctx: CheckContext) -> Iterator[Finding]:
    """One line for a list in which (nearly) everything is approved: maybe it was approved without looking."""
    passages = ctx.parallel_passages or []
    approved = sum(entry.status == "F" for entry in passages)
    if len(passages) >= ALL_APPROVED_MIN_ENTRIES and approved >= ALL_APPROVED_SHARE * len(passages):
        yield _finding(places.PARALLEL_PASSAGES, "Status", "all approved",
                       f"{approved} of {len(passages)} parallel passages are approved "
                       f"({100 * approved // len(passages)}%): check that they were really compared")


def check_approvals(usage: UsageCounter, ctx: CheckContext) -> Iterator[Finding]:
    """Approved entries that look wrong, rejected entries used very often, settings that turn a check off."""
    yield from _switched_off(usage, ctx)
    yield from _all_approved(ctx)
    yield from _characters(usage, ctx)
    yield from _punctuation(usage, ctx)
    yield from _rejected_but_used(usage, ctx)
    yield from _wordlist(ctx)
    yield from _hyphenation(ctx)

