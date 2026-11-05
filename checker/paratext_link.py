"""Links from the HTML report to Paratext: a click on "MAT 5:3" makes Paratext show that verse.

The report links look like `scripturechecker:<project>/MAT%205:3?vrs=4`. Windows starts this program with the link
(the URL protocol is registered under HKCU\\Software\\Classes, no admin rights needed); the program then sends the
reference the way Paratext windows send it to each other ("SantaFe focus"): the reference is written to
HKCU\\Software\\SantaFe\\Focus\\ScriptureReference and the registered window message "SantaFeFocus" is posted to
all windows. Paratext moves the windows of scroll group A. The message names no project, so the program reads the
window titles of Paratext ("<project>: MAT 5:3 (Standard Translation)") to see that the project window moved.

Standard library only (winreg, ctypes); Windows only.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote

from checker.versification import to_english

PROTOCOL = "scripturechecker"
TITLE = "Scripture checker"
ENGLISH = "4"  # Settings.xml <Versification>
_FOCUS_KEY = r"Software\SantaFe\Focus\ScriptureReference"
_FOCUS_MESSAGE = "SantaFeFocus"
_HWND_BROADCAST = 0xFFFF
_TITLE_RE = re.compile(r"^(.+?): ([0-9A-Z]{3}) (\d+):(\d+)")
_REF_RE = re.compile(r"^([0-9A-Z]{3}) (\d+):(\d+)$")
WAIT_SECONDS = 1.5  # time for Paratext to move its windows
MAX_TRIES = 4  # sends to find the verse in a project that is not in the English versification


def make_link(project: str, reference: str, versification: str = "") -> str:
    """The link of one reference ("MAT 5:3"); the HTML page builds the same links in JavaScript."""
    link = f"{PROTOCOL}:{quote(project, safe='')}/{quote(reference, safe=':')}"
    return f"{link}?vrs={quote(versification)}" if versification else link


def parse_link(url: str) -> tuple[str, str, str] | None:
    """(project, reference, versification) of a link, or None if it is not a link of this program."""
    if not url.lower().startswith(f"{PROTOCOL}:"):
        return None
    rest = url[len(PROTOCOL) + 1:].lstrip("/")
    rest, _, query = rest.partition("?")
    versification = next((unquote(value) for key, _, value in (part.partition("=") for part in query.split("&"))
                          if key == "vrs"), "")
    project, _, reference = rest.rstrip("/").partition("/")
    project, reference = unquote(project), " ".join(unquote(reference).split())
    if not project or not _REF_RE.match(reference):
        return None
    return project, reference, versification


def window_reference(title: str) -> tuple[str, str] | None:
    """(project, "MAT 5:3") shown in a Paratext window title, or None."""
    match = _TITLE_RE.match(title)
    return (match.group(1), f"{match.group(2)} {match.group(3)}:{match.group(4)}") if match else None


def shows(shown: str, wanted: str) -> bool:
    """The window shows the wanted verse; verse 0 (before verse 1) also counts as verse 1."""
    if shown == wanted:
        return True
    book, chapter, verse = _REF_RE.match(wanted).groups()
    return verse == "0" and shown == f"{book} {chapter}:1"


# ------------------------------------------------------------------------------------------------ Windows part ---

def handler_command() -> str:
    """The command Windows runs for a link: this exe, or pythonw with checker_app.py when run from the source."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"'
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    app = Path(__file__).resolve().parent.parent / "checker_app.py"
    return f'"{pythonw if pythonw.is_file() else python}" "{app}" "%1"'


def register() -> bool:
    """Register the URL protocol for the current user (again, if this program has moved). False = not possible."""
    try:
        import winreg
    except ImportError:
        return False
    try:
        base = rf"Software\Classes\{PROTOCOL}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f"URL:{TITLE}")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\shell\open\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, handler_command())
        return True
    except OSError:
        return False


def _paratext_windows() -> list[tuple[int, list[str]]]:
    """(main window, titles of its child windows) for every running Paratext."""
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def text(hwnd) -> str:
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def program(hwnd) -> str:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        buffer, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
        kernel32.CloseHandle(handle)
        return Path(buffer.value).name.lower()

    found: list[tuple[int, list[str]]] = []

    @callback_type
    def top(hwnd, _):
        if user32.IsWindowVisible(hwnd) and program(hwnd) == "paratext.exe" and text(hwnd):
            titles: list[str] = []

            @callback_type
            def child(inner, __):
                title = text(inner)
                if window_reference(title):
                    titles.append(title)
                return True

            user32.EnumChildWindows(hwnd, child, 0)
            found.append((hwnd, titles))
        return True

    user32.EnumWindows(top, 0)
    return found


def _send(reference: str) -> None:
    import ctypes
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _FOCUS_KEY) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, reference)
    user32 = ctypes.windll.user32
    user32.PostMessageW(_HWND_BROADCAST, user32.RegisterWindowMessageW(_FOCUS_MESSAGE), 1, 0)


def _to_front(hwnd: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    # Windows lets a program bring another window to the front only after a key press: press and release Alt.
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)


def next_try(sent: str, wanted: str, shown: str) -> str | None:
    """The reference to send next. Paratext reads a sent reference in the English versification and shows it in the
    versification of the project (English PSA 51:1 = PSA 50:3 in a project with Septuagint psalm numbers), so the
    difference between the wanted and the shown verse is added to what was sent. None = no better guess."""
    sent_m, wanted_m, shown_m = (_REF_RE.match(ref) for ref in (sent, wanted, shown))
    if not (sent_m and wanted_m and shown_m) or shown_m.group(1) != wanted_m.group(1):
        return None
    chapter = int(sent_m.group(2)) + int(wanted_m.group(2)) - int(shown_m.group(2))
    verse = int(sent_m.group(3)) + int(wanted_m.group(3)) - int(shown_m.group(3))
    guess = f"{wanted_m.group(1)} {chapter}:{verse}"
    return guess if chapter >= 1 and verse >= 0 and guess != sent else None


def _project_refs(project: str) -> list[str]:
    return [ref for _, titles in _paratext_windows() for name, ref in filter(None, map(window_reference, titles))
            if name.lower() == project.lower()]


def _send_and_read(project: str, reference: str, before: list[str]) -> list[str]:
    """Send a reference and wait until a window of the project shows another verse (or the time is over)."""
    _send(reference)
    end = time.monotonic() + WAIT_SECONDS
    shown = before
    while time.monotonic() < end:
        time.sleep(0.1)
        shown = _project_refs(project)
        if shown != before:
            time.sleep(0.1)  # Paratext may still be moving
            return _project_refs(project)
    return shown


def go_to(url: str) -> str:
    """Make Paratext show the verse of a link. Returns "" when it worked, else a message for the user."""
    parsed = parse_link(url)
    if not parsed:
        return f"This link cannot be read: {url}"
    project, reference, versification = parsed
    windows = _paratext_windows()
    if not windows:
        return f"Paratext is not open. Open it and the project {project}, then click {reference} again."
    shown = _project_refs(project)
    _to_front(windows[0][0])
    if not shown:
        _send(reference)
        return (f"The project {project} is not open in Paratext. Other windows went to {reference}. "
                f"Open {project} in Paratext and click {reference} again.")
    # Paratext reads a sent reference in the English versification: convert it (custom.vrs of the project is not
    # known here; the tries below correct what is left).
    book, chapter, verse = _REF_RE.match(reference).groups()
    english = to_english((book, int(chapter), int(verse)), versification) if versification else None
    sent = f"{english[0]} {english[1]}:{english[2]}" if english else reference
    for _ in range(MAX_TRIES if versification != ENGLISH else 1):
        before = shown
        shown = _send_and_read(project, sent, before)
        if any(shows(ref, reference) for ref in shown):
            return ""
        # The window that moved shows where the sent reference landed in the project.
        moved = [ref for ref in shown if ref not in before] or shown
        sent = next((guess for ref in moved if (guess := next_try(sent, reference, ref))), None)
        if sent is None:
            break
    return (f"The window of {project} did not go to {reference} (it shows {', '.join(shown)}). "
            "Maybe the window is in another scroll group: in Paratext, set the scroll group of the window to A.")


def handle(url: str) -> None:
    """Entry point for a link (no main window); problems are shown in a message box."""
    try:
        message = go_to(url)
    except Exception as error:  # shown to the user: nobody sees a console here
        message = f"Could not go to the verse: {error}"
    if message:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, TITLE, 0x40)  # MB_ICONINFORMATION
        except (ImportError, AttributeError, OSError):
            print(message)
