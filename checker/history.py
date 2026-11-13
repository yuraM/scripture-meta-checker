"""What changed since the last run, and the problems a user accepted ("this is not a problem").

Each run folder gets `findings.json`: the checks and books of the run and every finding. The next run compares its
findings with the newest earlier run that has this file: a finding is "new" when the earlier run had no finding with
the same check, book, chapter:verse, severity and message (the text around it may change); "fixed" when it was there
and is gone now. Only checks and books of both runs are compared.

Accepted findings are kept in `accepted.json` of the report folder (the parent of the run folders), so they stay
accepted in later runs; they are hidden from the reports. The HTML report accepts a problem with a link
`scripturechecker:accept?run=...&check=...&severity=...&message=...` (`&undo=1` takes it back; `&clear=all`, the button "Undo all Accept" of index.html, clears the list): Windows starts this
program with the link (the same URL protocol as the links to Paratext). The window can clear the list.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs

from checker.model import ERROR, Finding

FINDINGS_FILE = "findings.json"
ACCEPTED_FILE = "accepted.json"
ACCEPT_PREFIX = "scripturechecker:accept?"
FORMAT_VERSION = 1
RUN_FOLDER_RE = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}(?:_\d+)?$")
LOCK_WAIT_SECONDS = 5.0

Key = tuple[str, str, str, str, str]  # check, book, chapter:verse, severity, message


def finding_key(finding: Finding) -> Key:
    return finding.check, finding.book, finding.ref, finding.severity, finding.message


@dataclass
class RunData:
    """What one run checked and found (the content of findings.json)."""
    checks: list[str]
    books: list[str] | None  # None = all books of the project
    errors_only: bool
    skipped: list[str]
    findings: list[Key]


@dataclass
class Change:
    """New findings of one check since the previous run, and how many of its findings are gone."""
    new: set[Key] = field(default_factory=set)
    fixed: int = 0


def run_sort_key(folder: Path) -> tuple[str, int]:
    return folder.name[:16], int(folder.name[17:] or 1)


def write_run_data(run: Path, data: RunData) -> None:
    content = {"version": FORMAT_VERSION, "checks": data.checks, "books": data.books,
               "errors_only": data.errors_only, "skipped": data.skipped,
               "findings": [list(key) for key in data.findings]}
    (run / FINDINGS_FILE).write_text(json.dumps(content, ensure_ascii=False, separators=(",", ":")),
                                     encoding="utf-8")


def read_run_data(run: Path) -> RunData | None:
    """The findings of a run folder; None when it has none (a run of an older version) or the file is damaged."""
    try:
        content = json.loads((run / FINDINGS_FILE).read_text(encoding="utf-8"))
        return RunData(list(content["checks"]), content["books"], bool(content["errors_only"]),
                       list(content.get("skipped", [])), [tuple(row) for row in content["findings"]])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def previous_run(report_dir: Path, current: Path | None = None) -> Path | None:
    """The newest run folder with findings.json, other than `current`."""
    if not report_dir.is_dir():
        return None
    runs = [p for p in report_dir.iterdir() if p.is_dir() and RUN_FOLDER_RE.match(p.name)
            and p != current and (p / FINDINGS_FILE).is_file()]
    return max(runs, key=run_sort_key, default=None)


def compare(previous: RunData, current: RunData) -> dict[str, Change]:
    """Check -> what changed; checks that are not in both runs (or could not run in one) are left out."""
    checks = (set(previous.checks) & set(current.checks)) - set(previous.skipped) - set(current.skipped)
    if previous.books is None:
        books = None if current.books is None else set(current.books)
    else:
        books = set(previous.books) if current.books is None else set(previous.books) & set(current.books)
    errors_only = previous.errors_only or current.errors_only

    def selected(keys: Iterable[Key]) -> set[Key]:
        return {key for key in keys if key[0] in checks and (books is None or key[1] in books)
                and (not errors_only or key[3] == ERROR)}

    before, now = selected(previous.findings), selected(current.findings)
    changes = {name: Change() for name in checks}
    for key in now - before:
        changes[key[0]].new.add(key)
    for key in before - now:
        changes[key[0]].fixed += 1
    return changes


# ------------------------------------------------------------------------------------------------ accepted ---

def accepted_path(report_dir: Path) -> Path:
    return report_dir / ACCEPTED_FILE


def read_accepted(report_dir: Path) -> set[Key]:
    try:
        content = json.loads(accepted_path(report_dir).read_text(encoding="utf-8"))
        return {tuple(row) for row in content["accepted"] if len(row) == 5}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def write_accepted(report_dir: Path, keys: Iterable[Key]) -> None:
    """Write the list (sorted, so the file changes little); an empty list removes the file."""
    path = accepted_path(report_dir)
    rows = sorted(keys)
    if not rows:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_suffix(".tmp")
    # One place per line: the file can be read (and changed) by hand.
    lines = ",\n".join(json.dumps(list(row), ensure_ascii=False) for row in rows)
    temporary.write_text(f'{{"version": {FORMAT_VERSION}, "accepted": [\n{lines}\n]}}\n', encoding="utf-8")
    os.replace(temporary, path)


def accepted_counts(report_dir: Path) -> Counter[str]:
    """Check -> number of accepted findings (for the window)."""
    return Counter(key[0] for key in read_accepted(report_dir))


def clear_accepted(report_dir: Path, check: str | None = None) -> None:
    """Forget the accepted findings of one check, or all of them."""
    with _Lock(report_dir):
        keep = {key for key in read_accepted(report_dir) if check is not None and key[0] != check}
        write_accepted(report_dir, keep)


def split_accepted(findings: Sequence[Finding], accepted: set[Key]) -> tuple[list[Finding], Counter[str]]:
    """(findings that are not accepted, check -> number of accepted findings left out)."""
    shown, hidden = [], Counter()
    for finding in findings:
        if finding_key(finding) in accepted:
            hidden[finding.check] += 1
        else:
            shown.append(finding)
    return shown, hidden


class _Lock:
    """Two clicks in the browser start two programs: only one changes accepted.json at a time."""

    def __init__(self, report_dir: Path) -> None:
        self.path = report_dir / (ACCEPTED_FILE + ".lock")

    def __enter__(self) -> None:
        end = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return
            except FileExistsError:
                if time.monotonic() > end:  # left by a program that stopped: take it over
                    return
                time.sleep(0.05)

    def __exit__(self, *_) -> None:
        self.path.unlink(missing_ok=True)


# ------------------------------------------------------------------------------------------------ the link ---

def is_accept_link(url: str) -> bool:
    return url.lower().startswith(ACCEPT_PREFIX)


def accept(url: str) -> str:
    """Accept (or with undo=1 take back) the problem of a link. Returns "" when it worked, else a message."""
    query = parse_qs(url[len(ACCEPT_PREFIX):], keep_blank_values=True)
    value = lambda name: query.get(name, [""])[0]  # noqa: E731
    run = Path(value("run"))
    check, severity, message = value("check"), value("severity"), value("message")
    # Only a run folder of this program, and only problems that are in its report, are written: a link from another
    # web page cannot write elsewhere.
    data = read_run_data(run) if value("run") and RUN_FOLDER_RE.match(run.name) else None
    if data is None:
        return f"The report folder was not found: {run}. Was it moved or deleted?"
    if value("clear") == "all":  # the button "Undo all Accept" of index.html
        clear_accepted(run.parent)
        return ""
    keys ={key for key in data.findings if key[0] == check and key[3] == severity and key[4] == message}
    if not keys:
        return f"This problem is not in the report of {run.name}."
    with _Lock(run.parent):
        accepted = read_accepted(run.parent)
        write_accepted(run.parent, accepted - keys if value("undo") == "1" else accepted | keys)
    return ""


def handle(url: str) -> None:
    """Entry point for an accept link (no window); a problem is shown in a message box."""
    try:
        message = accept(url)
    except Exception as error:  # nobody sees a console here
        message = f"Could not save the accepted problem: {error}"
    if message:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "Scripture checker", 0x40)
        except (ImportError, AttributeError, OSError):
            print(message)
