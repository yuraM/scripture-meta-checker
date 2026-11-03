"""Shared types: findings, analysed segments and the check context."""
from __future__ import annotations

from dataclasses import dataclass

from checker.hyphenation import HyphenationList
from checker.languages import LanguageProfile, profile_for
from checker.settings import ProjectSettings
from checker.spelling import SpellingList
from checker.tokens import Run, join_words, make_word_char_predicate, split_runs
from checker.usfm import Segment

ERROR = "error"
WARNING = "warning"
CONTEXT_WIDTH = 20


@dataclass(frozen=True)
class Finding:
    book: str
    ref: str
    severity: str
    check: str
    # The offending character / pattern / word, used to group findings in --unique mode.
    item: str
    message: str
    context: str

    def format(self) -> str:
        line = f"{self.book} {self.ref}  {self.severity}  {self.check}  {self.message}"
        return f"{line}  [{self.context}]" if self.context else line


@dataclass(frozen=True)
class Analysis:
    segment: Segment
    runs: list[Run]
    words: list[Run]

    def finding(self, offset: int, length: int, severity: str, check: str, item: str, message: str) -> Finding:
        text = self.segment.text
        left = max(offset - CONTEXT_WIDTH, 0)
        right = min(offset + length + CONTEXT_WIDTH, len(text))
        return Finding(
            book=self.segment.book,
            ref=self.segment.ref_at(offset),
            severity=severity,
            check=check,
            item=item,
            message=message,
            context=text[left:right],
        )


class CheckContext:
    def __init__(
        self,
        settings: ProjectSettings,
        spelling: SpellingList,
        hyphenation: HyphenationList | None = None,
        language: LanguageProfile | None = None,
    ) -> None:
        self.settings = settings
        self.spelling = spelling
        self.hyphenation = hyphenation
        self.language = language or profile_for(settings.language_iso_code)
        # Words of all \toc1-3 names of the project; filled before the checks run.
        self.book_name_words: frozenset[str] = frozenset()
        # ParallelPassageStatus.xml entries (checker.parallels.PassageStatus); None = the project has no such file.
        self.parallel_passages: list | None = None
        # Check name -> why it could not run (shown in its report).
        self.skipped: dict[str, str] = {}
        # Check name -> a note shown under its counts, e.g. what was not listed and why.
        self.notes: dict[str, str] = {}
        # checker.terms.TermData; None = the project folder has no terms files.
        self.terms = None
        self.terms_problem = ""  # why ctx.terms is None
        self.is_word_char = make_word_char_predicate(settings.punctuation_characters)
        self.abbreviations = frozenset(a.lower() for a in settings.abbreviations)
        self.repeatable_words = settings.repeatable_words | {w.lower() for w in settings.repeatable_words}
        self.non_repeatable_words = settings.non_repeatable_words | {w.lower() for w in settings.non_repeatable_words}
        # What may follow the last punctuation of a paragraph: closing quotes and brackets.
        self.closing_marks = frozenset(
            ch for level in settings.quote_levels for mark in level for ch in mark
        ) | {close for _, close in settings.pairs}
        # After these a capital is expected anyway: sentence end, quotes, opening brackets.
        self.sentence_starters = (
            settings.sentence_final_punctuation
            | {ch for level in settings.quote_levels for mark in level for ch in mark}
            | {ch for continuer in settings.quote_continuers for ch in continuer}
            | {open_ for open_, _ in settings.pairs}
        )

    def analyse(self, segment: Segment) -> Analysis:
        runs = split_runs(segment.text, self.is_word_char)
        return Analysis(segment, runs, join_words(runs, self.settings.word_medial_punctuation))
