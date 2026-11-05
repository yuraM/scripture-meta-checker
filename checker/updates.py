"""Is there a newer release on GitHub? The window asks once at start, in the background.

Only the public release list is read (no data about the user or the projects is sent). Without internet, or on any
error, the answer is "no": the program works as before. Standard library only.
"""
from __future__ import annotations

import json
import re
import urllib.request

RELEASES_PAGE = "https://github.com/yuraM/scripture-meta-checker/releases/latest"
LATEST_API = "https://api.github.com/repos/yuraM/scripture-meta-checker/releases/latest"
TIMEOUT_SECONDS = 5


def version_numbers(text: str) -> tuple[int, ...]:
    """"v1.10" -> (1, 10); () if there are no numbers."""
    return tuple(int(part) for part in re.findall(r"\d+", text))


def is_newer(latest: str, current: str) -> bool:
    latest_numbers = version_numbers(latest)
    return bool(latest_numbers) and latest_numbers > version_numbers(current)


def newer_release(current: str) -> tuple[str, str] | None:
    """(tag, page) of the newest release when it is newer than `current`, else None (also without internet)."""
    request = urllib.request.Request(LATEST_API, headers={"Accept": "application/vnd.github+json",
                                                          "User-Agent": "scripture-checker"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = json.load(response)
    except Exception:  # no internet, proxy, rate limit, bad answer: just no notice
        return None
    tag = str(data.get("tag_name", ""))
    return (tag, str(data.get("html_url") or RELEASES_PAGE)) if is_newer(tag, current) else None
