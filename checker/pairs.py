"""Matched pairs check (Settings.xml Pairs, e.g. "(/) [/] {/}"), book level.

Like quotes, the scripture flow of a book shares one stack, because ClosedByParagraph=No
lets a pair span paragraphs; headings and notes are checked one segment at a time.
"""
from __future__ import annotations

from collections.abc import Iterator

from checker.model import ERROR, WARNING, Analysis, CheckContext, Finding
from checker.quotes import is_isolated

CHECK = "pairs"


class _PairStack:
    def __init__(self, ctx: CheckContext) -> None:
        settings = ctx.settings
        # Quote marks may also be listed in Pairs (“/”), but only the quotes check knows continuers and apostrophes.
        quote_marks = {mark for level in settings.quote_levels for mark in level}
        pairs = [(open_, close) for open_, close in settings.pairs if not {open_, close} & quote_marks]
        self.closer_of = dict(pairs)
        self.opener_of = {close: open_ for open_, close in pairs}
        # Characters approved to occur unmatched are reported as warnings only.
        self.unmatched_ok = settings.unmatched_pairing_characters
        self.open: list[tuple[Analysis, int, str]] = []

    def severity(self, mark: str) -> str:
        return WARNING if mark in self.unmatched_ok else ERROR

    def feed(self, analysis: Analysis) -> Iterator[Finding]:
        for offset, ch in enumerate(analysis.segment.text):
            if ch in self.closer_of:
                self.open.append((analysis, offset, ch))
            elif ch in self.opener_of:
                yield from self._close(analysis, offset, ch)

    def _close(self, analysis: Analysis, offset: int, mark: str) -> Iterator[Finding]:
        opener = self.opener_of[mark]
        index = next((i for i in range(len(self.open) - 1, -1, -1) if self.open[i][2] == opener), None)
        if index is None:
            yield analysis.finding(offset, 1, self.severity(mark), CHECK, mark,
                                   f"'{mark}' has no opening '{opener}'")
            return
        for inner, inner_offset, inner_mark in self.open[index + 1:]:
            yield inner.finding(inner_offset, 1, self.severity(inner_mark), CHECK, inner_mark,
                                f"'{inner_mark}' must be closed before '{mark}'")
        del self.open[index:]

    def finish(self) -> Iterator[Finding]:
        for analysis, offset, mark in self.open:
            yield analysis.finding(offset, 1, self.severity(mark), CHECK, mark,
                                   f"'{mark}' is opened but never closed ('{self.closer_of[mark]}' is missing)")
        self.open = []


def check_pairs(analyses: list[Analysis], ctx: CheckContext) -> Iterator[Finding]:
    if not ctx.settings.pairs:
        return
    flow = _PairStack(ctx)
    for analysis in analyses:
        if analysis.segment.in_note or is_isolated(analysis):
            single = _PairStack(ctx)
            yield from single.feed(analysis)
            yield from single.finish()
        else:
            yield from flow.feed(analysis)
    yield from flow.finish()
