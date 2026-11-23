"""Key, role and run records: the window talks to scripturechecker.org (the contract is API.md of the site).

- The window does not start without a key; any key is accepted (the command line needs none and sends nothing).
- At start the window asks the site for the role of the key (`user`, `beta`, `admin`) in the background.
  `beta`/`admin` see all checks and the role is kept for 30 days without an answer; then, or for an unknown key, the
  role is `user`: only the released checks are shown.
- After each run of the window a record is sent: key, version, time, seconds and the numbers of errors and warnings
  per check (checks marked "not checked" are left out). No project name, no text, no file names.
  Records that could not be sent wait in a queue file and go with the next record or the next start.

The program never waits for the site: requests run in the background with a short timeout, and any error is
"no answer". Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path

SITE = "https://scripturechecker.org"
ROLE_PATH = "/api/v1/role"
RUNS_PATH = "/api/v1/runs"
TIMEOUT_SECONDS = 5
HEADERS = {"User-Agent": "scripture-checker", "Content-Type": "application/json", "Accept": "application/json"}
ROLES = ("user", "beta", "admin")
FULL_ROLES = ("beta", "admin")  # see all checks
KEEP_ROLE = timedelta(days=30)  # beta/admin without an answer from the site
MAX_RUNS_PER_REQUEST = 100  # API.md
MAX_QUEUED = 2000  # older records are dropped: the queue file stays small
MAX_AGE = timedelta(days=2 * 365)  # the site does not save older records
DATA_FOLDER = Path(os.environ.get("APPDATA") or Path.home()) / "Scripture checker"
KEY_FILE = "key.json"
QUEUE_FILE = "runs_queue.json"

# The checks a `user` sees: the checks of release v1.0.2. hyphenation-list and term-renderings were parts of
# hyphenation and terms then (split 2026-11-17). For each next release the user says which checks are added here.
RELEASED_CHECKS = frozenset({
    "lists", "approvals", "term-lists", "hyphenation-list", "term-renderings", "unused",
    "usfm", "book-titles", "normalization", "special-spaces",
    "characters", "scripts", "punctuation", "spacing", "numbers", "quotes", "pairs", "paragraph-final",
    "spelling", "mixed-capitalization", "capitalization", "repeated-words", "ordinals", "hyphenation",
    "references", "footnotes", "terms", "parallel-changes", "parallel-differences",
    "variants", "name-case", "styled-words", "divine-name",
})

# (HTTP status or 0 for no answer, the JSON answer or None)
Post = Callable[[str, dict], tuple[int, object]]

_lock = threading.Lock()  # one writer of the files at a time (the window sends in background threads)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    """2026-11-23T14:05:00Z"""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: object) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def clean_key(text: str) -> str:
    """The key as typed, without spaces at the ends and with inner spaces joined ("sck 7k2m" stays readable)."""
    return " ".join(text.split())


def same_key(a: str, b: str) -> bool:
    """Keys are compared without case, spaces or dashes (API.md)."""
    def simple(key: str) -> str:
        return "".join(ch for ch in key.upper() if not ch.isspace() and ch != "-")
    return simple(a) == simple(b)


# --- files -------------------------------------------------------------------------------------------------------

def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    """Write a temporary file and put it in place: a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporary, path)


def load_key_state(folder: Path = DATA_FOLDER) -> dict:
    """{"key": ..., "role": ..., "role_time": ISO time of the answer}; {} when no key was typed yet."""
    state = _read_json(folder / KEY_FILE, {})
    return state if isinstance(state, dict) and isinstance(state.get("key"), str) and state["key"].strip() else {}


def save_key(key: str, folder: Path = DATA_FOLDER) -> dict:
    """A new key: the role of the old one is not kept. Returns the new state."""
    with _lock:
        old = load_key_state(folder)
        state = {"key": clean_key(key)}
        if old and same_key(old["key"], key) and old.get("role"):  # the same key typed again
            state.update(role=old["role"], role_time=old.get("role_time"))
        _write_json(folder / KEY_FILE, state)
    return state


def save_role(key: str, role: str, moment: datetime, folder: Path = DATA_FOLDER) -> bool:
    """Keep the answer of the site; False when the key was changed meanwhile (the answer is for the old key)."""
    with _lock:
        state = load_key_state(folder)
        if not state or not same_key(state["key"], key):
            return False
        state.update(role=role, role_time=iso(moment))
        _write_json(folder / KEY_FILE, state)
    return True


def kept_role(state: dict, moment: datetime) -> str:
    """The role to use now: beta/admin while the answer is younger than 30 days, else user."""
    role = state.get("role")
    answered = parse_iso(state.get("role_time"))
    if role in FULL_ROLES and answered and answered <= moment + timedelta(days=1) and moment - answered < KEEP_ROLE:
        return role
    return "user"


def visible_checks(role: str, checks: Iterable[str]) -> list[str]:
    """The checks a role may run, in the given order."""
    return list(checks) if role in FULL_ROLES else [name for name in checks if name in RELEASED_CHECKS]


# --- the site ----------------------------------------------------------------------------------------------------

def post_json(path: str, body: dict) -> tuple[int, object]:
    """POST to the site; (0, None) without internet, on a timeout or any other error."""
    request = urllib.request.Request(SITE + path, data=json.dumps(body).encode("utf-8"), headers=HEADERS,
                                     method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:  # 400, 429, 5xx: the status is the answer
        try:
            raw = error.read()
        except Exception:
            raw = b""
        status = error.code
    except Exception:  # no internet, proxy, timeout, certificate
        return 0, None
    try:
        return status, json.loads(raw.decode("utf-8")) if raw else None
    except ValueError:
        return status, None


def ask_role(key: str, version: str, post: Post = post_json) -> str | None:
    """The role the site gives the key; None = no answer (keep what is kept)."""
    status, answer = post(ROLE_PATH, {"key": key, "version": version})
    if status == 200 and isinstance(answer, dict) and answer.get("role") in ROLES:
        return answer["role"]
    return None


def refresh_role(version: str, folder: Path = DATA_FOLDER, post: Post = post_json,
                 moment: datetime | None = None) -> str | None:
    """Ask the site and keep its answer. Returns the role to use now, or None when nothing changed."""
    state = load_key_state(folder)
    if not state:
        return None
    role = ask_role(state["key"], version, post)
    if role is None or not save_role(state["key"], role, moment or now_utc(), folder):
        return None
    return role


# --- run records -------------------------------------------------------------------------------------------------

def run_record(results, version: str, seconds: float, moment: datetime | None = None) -> dict:
    """The record of one run of the window. `results`: CheckResult of the run (name, errors, warnings, skipped)."""
    checks = {r.name: {"errors": int(r.errors), "warnings": int(r.warnings)} for r in results if not r.skipped}
    return {"id": str(uuid.uuid4()), "time": iso(moment or now_utc()), "version": version[:32],
            "seconds": round(max(seconds, 0.0), 1), "checks": checks}


def _load_queue(folder: Path) -> dict:
    queue = _read_json(folder / QUEUE_FILE, {})
    if not isinstance(queue, dict) or not isinstance(queue.get("runs"), list):
        queue = {"runs": []}
    return queue


def add_record(key: str, record: dict, folder: Path = DATA_FOLDER) -> None:
    """Keep a record in the queue until the site has it."""
    with _lock:
        queue = _load_queue(folder)
        queue["runs"] = (queue["runs"] + [{"key": key, "run": record}])[-MAX_QUEUED:]
        _write_json(folder / QUEUE_FILE, queue)


def _body_hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()


def send_queue(folder: Path = DATA_FOLDER, post: Post = post_json, moment: datetime | None = None) -> int:
    """Send the kept records, up to 100 per request and grouped by key. Returns how many the site took.

    200: the sent records are forgotten (saved, duplicates and rejected alike). 400: they are kept, but the same body
    is not sent again (only when something changed). No answer, 429, 5xx: kept for the next time.
    """
    moment = moment or now_utc()
    with _lock:  # one sender at a time; the requests are short (5 s timeout)
        queue = _load_queue(folder)
        runs = [item for item in queue["runs"] if isinstance(item, dict) and isinstance(item.get("run"), dict)
                and isinstance(item.get("key"), str)]
        # The site does not save records older than 2 years: no need to keep them.
        runs = [item for item in runs if (parse_iso(item["run"].get("time")) or moment) > moment - MAX_AGE]
        bad = set(queue.get("bad", []))
        seen: set[str] = set()  # bodies of this time; older bad bodies are forgotten
        taken = 0
        for key in dict.fromkeys(item["key"] for item in runs):
            mine = [item for item in runs if item["key"] == key]
            for start in range(0, len(mine), MAX_RUNS_PER_REQUEST):
                part = mine[start:start + MAX_RUNS_PER_REQUEST]
                body = {"key": key, "runs": [item["run"] for item in part]}
                digest = _body_hash(body)
                seen.add(digest)
                if digest in bad:
                    continue
                status, _answer = post(RUNS_PATH, body)
                if status == 200:
                    sent = {id(item) for item in part}
                    runs = [item for item in runs if id(item) not in sent]
                    taken += len(part)
                elif status == 400:
                    bad.add(digest)
                else:  # no answer, 429, 5xx: try again later, also the other parts
                    _write_json(folder / QUEUE_FILE, {"runs": runs, "bad": sorted(bad)})
                    return taken
        _write_json(folder / QUEUE_FILE, {"runs": runs, "bad": sorted(bad & seen)})
    return taken


def queued(folder: Path = DATA_FOLDER) -> int:
    return len(_load_queue(folder)["runs"])
