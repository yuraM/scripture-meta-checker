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

PROTOCOL = "scripturechecker"
TITLE = "Scripture checker"
ENGLISH, ORIGINAL = "4", "1"  # Settings.xml <Versification>
_FOCUS_KEY = r"Software\SantaFe\Focus\ScriptureReference"
_FOCUS_MESSAGE = "SantaFeFocus"
_HWND_BROADCAST = 0xFFFF
_TITLE_RE = re.compile(r"^(.+?): ([0-9A-Z]{3}) (\d+):(\d+)")
_REF_RE = re.compile(r"^([0-9A-Z]{3}) (\d+):(\d+)$")
WAIT_SECONDS = 1.5  # time for Paratext to move its windows


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


def english_reference(reference: str, versification: str) -> str | None:
    """The reference in the English versification, for a project in the Original versification (eng.vrs)."""
    if versification != ORIGINAL:
        return None
    from checker.versification import original_to_project
    book, chapter, verse = _REF_RE.match(reference).groups()
    mapped = original_to_project(Path()).get((book, int(chapter), int(verse)))
    return f"{mapped[0]} {mapped[1]}:{mapped[2]}" if mapped else None


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


def _project_shows(project: str, wanted: str) -> tuple[bool, list[str]]:
    """(a window of the project shows the verse, the references its windows show)."""
    shown = [ref for _, titles in _paratext_windows() for name, ref in filter(None, map(window_reference, titles))
             if name.lower() == project.lower()]
    return any(shows(ref, wanted) for ref in shown), shown


def go_to(url: str) -> str:
    """Make Paratext show the verse of a link. Returns "" when it worked, else a message for the user."""
    parsed = parse_link(url)
    if not parsed:
        return f"This link cannot be read: {url}"
    project, reference, versification = parsed
    windows = _paratext_windows()
    if not windows:
        return f"Paratext is not open. Open it and the project {project}, then click {reference} again."
    has_project = any(name.lower() == project.lower()
                      for _, titles in windows for name, _ in filter(None, map(window_reference, titles)))
    _to_front(windows[0][0])
    tries = [reference]
    english = english_reference(reference, versification)
    if english and english != reference:
        tries.append(english)
    shown: list[str] = []
    for sent in tries:
        _send(sent)
        end = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < end:
            done, shown = _project_shows(project, reference)
            if done:
                return ""
            time.sleep(0.1)
    if not has_project:
        return (f"The project {project} is not open in Paratext. Other windows went to {reference}. "
                f"Open {project} in Paratext and click {reference} again.")
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
