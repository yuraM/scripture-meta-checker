"""Quotation marks: pairing and nesting levels, following the project's quote settings.

Settings.xml defines the marks per level (Quotes, InnerQuotes, InnerInnerQuotes; deeper levels
alternate the last two), whether an open quote is repeated at the start of a continuing
paragraph (ContinueQuotes + Continuer..., where: ContinueAt) and QuoteClosesAllQuoteLevels.

Scripture paragraphs of a book form one flow (a quote may span paragraphs and chapters).
Headings, titles, introductions and notes are checked one segment at a time.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from checker.model import ERROR, WARNING, Analysis, CheckContext, Finding
from checker.settings import ProjectSettings

CHECK = "quotes"
# Paragraph styles whose segments are checked on their own (headings, titles, introduction).
ISOLATED_STYLES = frozenset({"h", "r", "d", "sp", "sr", "mr", "cl", "cd", ""})
ISOLATED_STYLE_PREFIXES = ("mt", "ms", "s", "toc", "i")


@dataclass
class _OpenQuote:
    mark: str
    analysis: Analysis
    offset: int
    continuation_reported: bool = False

    @property
    def where(self) -> str:
        return f"{self.analysis.segment.book} {self.analysis.segment.ref_at(self.offset)}"


class _QuoteRules:
    def __init__(self, settings: ProjectSettings) -> None:
        self.levels = settings.quote_levels
        self.openers = {open_mark for open_mark, _ in self.levels}
        self.closers = {close_mark for _, close_mark in self.levels}
        self.closer_of = {}
        for open_mark, close_mark in self.levels:
            self.closer_of.setdefault(open_mark, close_mark)
        # Longest first, so multi-character marks win over their prefixes.
        self.marks = sorted(self.openers | self.closers, key=len, reverse=True)
        self.continuers = settings.quote_continuers
        self.continue_quotes = settings.continue_quotes
        self.continue_at = settings.continue_at
        self.closes_all = settings.quote_closes_all_levels

    def level(self, depth: int) -> int:
        """Level index for a nesting depth; beyond the defined levels the last two alternate."""
        count = len(self.levels)
        if depth < count or count < 2:
            return min(depth, count - 1)
        return count - 2 + (depth - count) % 2

    def continuer(self, depth: int) -> str:
        level = self.level(depth)
        return self.continuers[level] if level < len(self.continuers) else ""

    def expects_continuation(self, analysis: Analysis) -> bool:
        if not self.continue_quotes:
            return False
        if not self.continue_at:
            return True
        segment = analysis.segment
        return segment.style in self.continue_at or f"{segment.previous_style}/{segment.style}" in self.continue_at

    def scan(self, text: str, start: int = 0) -> Iterator[tuple[int, str, bool]]:
        """Yield (offset, mark, between_letters) for every quotation mark."""
        index = start
        while index < len(text):
            mark = next((m for m in self.marks if text.startswith(m, index)), None)
            if not mark:
                index += 1
                continue
            end = index + len(mark)
            between_letters = index > 0 and end < len(text) and text[index - 1].isalpha() and text[end].isalpha()
            yield index, mark, between_letters
            index = end

    def is_opening(self, text: str, offset: int, mark: str) -> bool:
        if mark not in self.closers:
            return True
        if mark not in self.openers:
            return False
        # The same mark opens and closes (e.g. straight quotes): decide by the surrounding spaces.
        before = text[offset - 1] if offset else " "
        after = text[offset + len(mark)] if offset + len(mark) < len(text) else " "
        return (before.isspace() or before in self.openers) and not after.isspace()


class _QuoteState:
    def __init__(self, rules: _QuoteRules, in_note: bool = False) -> None:
        self.rules = rules
        # Notes quote fragments of the text with its marks: they may start or end inside a
        # quote ("Or “I have been given ... to") and keep inner marks ("‘You will ...’").
        # There the level is not checked and unpaired marks are only warnings.
        self.check_levels = not in_note
        self.severity = WARNING if in_note else ERROR
        self.suffix = " (in a footnote)" if in_note else ""
        self.stack: list[_OpenQuote] = []

    def _finding(self, analysis: Analysis, offset: int, mark: str, message: str) -> Finding:
        return analysis.finding(offset, len(mark), self.severity, CHECK, mark, message + self.suffix)

    def feed(self, analysis: Analysis, in_flow: bool) -> Iterator[Finding]:
        text = analysis.segment.text
        start = 0
        if in_flow and self.stack and self.rules.continue_quotes:
            start, finding = self._continuation(analysis)
            if finding:
                yield finding
        for offset, mark, between_letters in self.rules.scan(text, start):
            if between_letters:
                # Usually an apostrophe ("Don’t"), unless it closes the open quote and a suffix
                # follows the mark (Indonesian "‘apel’mu").
                if self.stack and self.rules.closer_of.get(self.stack[-1].mark) == mark:
                    self.stack.pop()
                continue
            if self.rules.is_opening(text, offset, mark):
                yield from self._open(analysis, offset, mark)
            else:
                yield from self._close(analysis, offset, mark)

    def finish(self) -> Iterator[Finding]:
        for quote in self.stack:
            yield self._finding(quote.analysis, quote.offset, quote.mark, f"quote mark '{quote.mark}' is opened but never closed")
        self.stack.clear()

    def _continuation(self, analysis: Analysis) -> tuple[int, Finding | None]:
        """Skip the continuers at the start of a paragraph that continues the open quotes.

        Continuers are accepted at any paragraph start; ContinueAt only says where their
        absence is reported.
        """
        text = analysis.segment.text
        # Opening brackets may come first: "(“ ‘These are ...".
        position = len(text) - len(text.lstrip("([{"))
        consumed: list[tuple[int, str]] = []  # (end position, continuer)
        for depth in range(len(self.stack)):
            continuer = self.rules.continuer(depth)
            rest = text[position:]
            stripped = position + len(rest) - len(rest.lstrip())
            if not continuer or not text.startswith(continuer, stripped):
                break
            position = stripped + len(continuer)
            consumed.append((position, continuer))
        # Only some levels repeated, and the last mark can open the next level: it is a new
        # inner quote, not a continuer ("“ ‘ ... saying, / “Give thanks ...").
        if 0 < len(consumed) < len(self.stack):
            next_opener = self.rules.levels[self.rules.level(len(self.stack))][0]
            if consumed[-1][1] == next_opener:
                consumed.pop()
        if consumed:
            return consumed[-1][0], None
        # Reported once per open quote: one missing closing mark must not flag every paragraph after it.
        if not self.rules.expects_continuation(analysis) or self.stack[0].continuation_reported:
            return 0, None
        self.stack[0].continuation_reported = True
        expected = self.rules.continuer(0)
        return 0, analysis.finding(
            0, 1, WARNING, CHECK, expected,
            f"this paragraph continues the quote from {self.stack[0].where}, so it must start with '{expected}'")

    def _open(self, analysis: Analysis, offset: int, mark: str) -> Iterator[Finding]:
        depth = len(self.stack)
        expected = self.rules.levels[self.rules.level(depth)][0]
        if mark != expected:
            if self.stack and mark == self.stack[-1].mark:
                top = self.stack.pop()
                yield self._finding(
                    analysis, offset, mark,
                    f"'{mark}' opens a new quote, but '{top.mark}' from {top.where} is still open "
                    f"('{self.rules.closer_of[top.mark]}' is missing, or the inner quote should use '{expected}')")
            elif self.check_levels:
                yield self._finding(analysis, offset, mark,
                                    f"wrong mark for quote level {depth + 1}: '{mark}', it should be '{expected}'")
        self.stack.append(_OpenQuote(mark, analysis, offset))

    def _close(self, analysis: Analysis, offset: int, mark: str) -> Iterator[Finding]:
        if not self.stack:
            yield self._finding(analysis, offset, mark, f"'{mark}' closes a quote, but no quote is open")
            return
        top = self.stack[-1]
        if self.rules.closer_of.get(top.mark) == mark:
            self.stack.pop()
            return
        matching = [i for i, quote in enumerate(self.stack) if self.rules.closer_of.get(quote.mark) == mark]
        if matching:
            index = matching[-1]
            if not (self.rules.closes_all and index == 0):
                inner = ", ".join(f"'{q.mark}' from {q.where}" for q in self.stack[index + 1:])
                yield self._finding(
                    analysis, offset, mark,
                    f"'{mark}' closes '{self.stack[index].mark}' from {self.stack[index].where} "
                    f"but {inner} is still open")
            del self.stack[index:]
        else:
            yield self._finding(
                analysis, offset, mark,
                f"'{mark}' cannot close '{top.mark}' from {top.where} "
                f"(it should be '{self.rules.closer_of.get(top.mark, '?')}')")
            self.stack.pop()


def is_isolated(analysis: Analysis) -> bool:
    segment = analysis.segment
    return (
        segment.in_note
        or segment.style in ISOLATED_STYLES
        or segment.style.startswith(ISOLATED_STYLE_PREFIXES)
    )


def check_quotes(analyses: list[Analysis], ctx: CheckContext) -> Iterator[Finding]:
    """All segments of one book, in order."""
    rules = _QuoteRules(ctx.settings)
    if not rules.levels:
        return
    flow = _QuoteState(rules)
    for analysis in analyses:
        if is_isolated(analysis):
            isolated = _QuoteState(rules, in_note=analysis.segment.in_note)
            yield from isolated.feed(analysis, in_flow=False)
            yield from isolated.finish()
        else:
            yield from flow.feed(analysis, in_flow=True)
    yield from flow.finish()
