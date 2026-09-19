"""Estimates written into the text itself: commit trailers and pull request bodies.

    Estimate: 2d
    Est: 4h
    /estimate 1w

The first one written wins. Put it in the branch's first commit — an empty one
is fine (`git commit --allow-empty -m "start PROJ-412" -m "Estimate: 2d"`).
A trailer that first shows up in a later commit was written after the work
began, and is refused as such.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from ..git import Commit
from ..model import Estimate, parse_estimate

_LINE = re.compile(
    r"^[ \t>*_#-]*(?:(?:estimate|est)[ \t]*[*_]*[ \t]*:|/estimate\b)[ \t]*[*_]*[ \t]*(\S.*?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def find(text: str | None) -> list[str]:
    """Every estimate written in `text`, in order."""
    return [m.group(1).strip("*_ ") for m in _LINE.finditer(text or "")]


def from_commits(commits: Iterable[Commit], me: set[str] | None = None) -> list[Estimate]:
    """Trailers in your own commits, oldest first. Someone else's trailer is someone else's promise."""
    out: list[Estimate] = []
    for c in sorted(commits, key=lambda c: c.at):
        if me and c.email not in me:
            continue
        out.extend(parse_estimate(said, "convention", c.at, c.short) for said in find(c.message))
    return out


def from_text(text: str | None, at: datetime | None, where: str, source: str = "convention") -> list[Estimate]:
    return [parse_estimate(said, source, at, where) for said in find(text)]
