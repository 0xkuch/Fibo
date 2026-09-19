"""`fibo say`: a local, append-only journal for people with no tracker and no convention.

Every line carries the SHA-256 of the line before it, and `ledger.head` holds
the hash of the last one. Edit, delete or reorder a line and the chain breaks;
`fibo doctor` says where.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from ..model import Estimate, parse_estimate, parse_time

PATH = Path(".fibo") / "ledger.jsonl"
HEAD = Path(".fibo") / "ledger.head"
GENESIS = "0" * 64


def _digest(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def read(root: Path) -> tuple[list[dict], list[tuple[int, str]]]:
    """(entries, problems). Each problem is (line number, what is wrong)."""
    path = root / PATH
    entries: list[dict] = []
    problems: list[tuple[int, str]] = []
    if not path.is_file():
        return entries, problems
    prev, last = GENESIS, 0
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            problems.append((n, "empty line"))
            continue
        last = n
        try:
            entry = json.loads(line)
            if not isinstance(entry, dict):
                raise ValueError
        except ValueError:
            problems.append((n, "not a ledger entry"))
            prev = _digest(line)
            continue
        if entry.get("prev") != prev:
            problems.append((n, "chain broken: the line before it was edited, removed or reordered"))
        entries.append({**entry, "_line": n})
        prev = _digest(line)
    head = root / HEAD
    if last:
        if not head.is_file():
            problems.append((last, "ledger.head is missing: the last line cannot be verified"))
        elif head.read_text(encoding="utf-8").strip() != prev:
            problems.append((last, "the last line was edited, removed or added by hand"))
    return entries, problems


def head(root: Path) -> str | None:
    """The hash of the last line, as `append` left it."""
    path = root / HEAD
    return path.read_text(encoding="utf-8").strip() if path.is_file() else None


def estimates(root: Path) -> dict[str, list[Estimate]]:
    entries, _ = read(root)
    out: dict[str, list[Estimate]] = {}
    for e in entries:
        key = str(e.get("key", "")).strip().upper()
        if key:
            out.setdefault(key, []).append(
                parse_estimate(e.get("said", ""), "ledger", parse_time(e.get("at")), f"ledger:{e['_line']}"))
    return out


def append(root: Path, key: str, said: str, email: str, at: datetime) -> dict:
    path = root / PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.is_file() else []
    entry = {"at": at.isoformat(timespec="seconds"), "email": email, "key": key,
             "prev": _digest(lines[-1]) if lines else GENESIS, "said": said}
    line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")
    (root / HEAD).write_text(_digest(line) + "\n", encoding="utf-8")
    return entry
