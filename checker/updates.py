"""Is there a newer release on GitHub? The window asks once at start, in the background.

Only the public release list is read (no data about the user or the projects is sent). Without internet, or on any
error, the answer is "no": the program works as before. Standard library only.

The Update button (exe only) downloads the checker.exe of the release next to the running exe, checks its size and
sha256 (both given by GitHub), and swaps the files: Windows cannot overwrite a running exe, but it can rename it, so
the running exe becomes `checker.old.exe` (removed at the next start) and the new file takes its name.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

RELEASES_PAGE = "https://github.com/yuraM/scripture-meta-checker/releases/latest"
LATEST_API = "https://api.github.com/repos/yuraM/scripture-meta-checker/releases/latest"
ASSET_NAME = "checker.exe"
TIMEOUT_SECONDS = 5
DOWNLOAD_TIMEOUT_SECONDS = 30  # per read, not for the whole file
CHUNK = 256 * 1024
HEADERS = {"User-Agent": "scripture-checker"}


class UpdateError(Exception):
    """The update could not be done; the running exe is not changed."""


@dataclass(frozen=True)
class Release:
    tag: str
    page: str
    url: str = ""  # download link of checker.exe; "" = the release has no exe
    size: int = 0
    sha256: str = ""  # lowercase hex; "" = GitHub gave no digest


def version_numbers(text: str) -> tuple[int, ...]:
    """"v1.10" -> (1, 10); () if there are no numbers."""
    return tuple(int(part) for part in re.findall(r"\d+", text))


def is_newer(latest: str, current: str) -> bool:
    latest_numbers = version_numbers(latest)
    return bool(latest_numbers) and latest_numbers > version_numbers(current)


def release_from_json(data: dict) -> Release:
    asset = next((a for a in data.get("assets") or [] if a.get("name") == ASSET_NAME), {})
    digest = str(asset.get("digest") or "")
    return Release(
        tag=str(data.get("tag_name", "")),
        page=str(data.get("html_url") or RELEASES_PAGE),
        url=str(asset.get("browser_download_url") or ""),
        size=int(asset.get("size") or 0),
        sha256=digest[len("sha256:"):].lower() if digest.startswith("sha256:") else "",
    )


def newer_release(current: str) -> Release | None:
    """The newest release when it is newer than `current`, else None (also without internet)."""
    request = urllib.request.Request(LATEST_API, headers={"Accept": "application/vnd.github+json", **HEADERS})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            release = release_from_json(json.load(response))
    except Exception:  # no internet, proxy, rate limit, bad answer: just no notice
        return None
    return release if is_newer(release.tag, current) else None


def old_exe(exe: Path) -> Path:
    return exe.with_name(f"{exe.stem}.old{exe.suffix}")


def new_exe(exe: Path) -> Path:
    return exe.with_name(f"{exe.name}.new")


def remove_old(exe: Path) -> None:
    """At start: delete what an earlier update left (the old exe, a broken download). Errors are ignored."""
    for path in (old_exe(exe), new_exe(exe)):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def download(release: Release, target: Path, progress: Callable[[int, int], None] = lambda done, total: None) -> None:
    """Download the exe of `release` into `target` and check it; on any problem `target` is removed: UpdateError."""
    if not release.url:
        raise UpdateError(f"The release has no {ASSET_NAME}.")
    digest = hashlib.sha256()
    done = 0
    try:
        request = urllib.request.Request(release.url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, target.open("wb") as out:
            total = release.size or int(response.headers.get("Content-Length") or 0)
            while chunk := response.read(CHUNK):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                progress(done, total)
        if release.size and done != release.size:
            raise UpdateError(f"The download is not complete ({done} of {release.size} bytes).")
        if release.sha256 and digest.hexdigest() != release.sha256:
            raise UpdateError("The downloaded file is damaged (its sha256 is not the one of the release).")
    except UpdateError:
        target.unlink(missing_ok=True)
        raise
    except Exception as error:  # network, disk full, no rights to write
        target.unlink(missing_ok=True)
        raise UpdateError(f"The download failed: {error}") from error


def replace_exe(exe: Path, new: Path) -> None:
    """Put `new` in the place of the running `exe`; the running one becomes the old exe. UpdateError on failure."""
    old = old_exe(exe)
    try:
        old.unlink(missing_ok=True)
        exe.rename(old)
    except OSError as error:
        raise UpdateError(f"The program file cannot be renamed: {error}") from error
    try:
        new.rename(exe)
    except OSError as error:
        old.rename(exe)  # put the running exe back
        raise UpdateError(f"The new program file cannot be put in place: {error}") from error


def update(release: Release, exe: Path, progress: Callable[[int, int], None] = lambda done, total: None) -> None:
    """Download and swap. After it the caller starts `exe` (the new version) and closes."""
    new = new_exe(exe)
    download(release, new, progress)
    replace_exe(exe, new)
