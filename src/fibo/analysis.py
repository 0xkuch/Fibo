"""One pass: config → history → sources → pairs → numbers.

No database, no index. Everything is recomputed on every run from what is on
disk (and, if you configured one, what your tracker says).
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import git, kinds, stats
from .clock import Zone
from .config import Config
from .model import Estimate, Task
from .pair import Keys, Outcome, branch_title, collect, evaluate, work_for
from .sources import convention, ledger
from .sources import fetch as fetch_trackers

REASONS = ("after_start", "no_branch", "not_duration", "points", "not_yours")


@dataclass
class Group:
    """"said 2 days — took 9 days": tasks that were given the same estimate."""

    estimate: Estimate
    n: int
    multiplier: float


@dataclass
class Analysis:
    root: Path
    cfg: Config
    mode: str  # work | calendar
    me: list[str]
    main: str | None
    outcomes: list[Outcome]
    warnings: list[str] = field(default_factory=list)
    summary: stats.Summary | None = None
    other: stats.Summary | None = None  # the other clock
    active: stats.Summary | None = None
    groups: list[Group] = field(default_factory=list)
    kinds: list[tuple[str, float, int]] = field(default_factory=list)
    drift: list[tuple[datetime, float, int]] = field(default_factory=list)
    points_as_hours: float | None = None
    zone: Zone = field(default_factory=Zone)

    @property
    def counted(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.counted]

    @property
    def closed(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.closed]

    @property
    def estimated(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.closed and o.estimate is not None]

    @property
    def excluded(self) -> Counter:
        return Counter(o.status for o in self.estimated if not o.counted)

    @property
    def assumed_points(self) -> bool:
        return any(o.estimate.is_points for o in self.counted if o.estimate)

    def find(self, key: str) -> Outcome | None:
        wanted = key.strip().upper()
        for o in self.outcomes:
            if o.key.upper() == wanted:
                return o
        return None


def analyze(path: Path | str, cfg: Config, *, mode: str = "work", offline: bool = False, refresh: bool = False,
            points_as_hours: float | None = None, repo: git.Repo | None = None) -> Analysis:
    repo = repo or git.open_repo(path, cfg.main_branch)
    me = set(cfg.emails)
    warnings = list(cfg.warnings)
    if not me:
        warnings.append("no email to call yours: set `git config user.email` or `emails` in .fibo.json")
    if repo.tip is None and repo.commits:
        warnings.append("no main branch found (main, master, trunk, develop): set `main_branch` in .fibo.json")
    rate = points_as_hours if points_as_hours is not None else cfg.points_as_hours

    tasks, problems = fetch_trackers(cfg, offline=offline, refresh=refresh) if cfg.trackers else ([], [])
    warnings += problems
    said = ledger.estimates(repo.root)

    zone = Zone((c.at, c.at.utcoffset()) for c in repo.commits.values() if c.email in me and not c.is_merge)
    numeric = any(t.key.startswith("#") for t in tasks)
    keys = Keys({t.key for t in tasks if not t.pr} | set(said), numeric)
    works = {k: work_for(k, us, me, cfg.calendar, zone)
             for k, us in collect(repo, keys, git.remotes(repo.root) or ["origin"]).items()}

    # A pull request body belongs to whatever landed with that PR number.
    by_pr = {w.pr: k for k, w in works.items() if w.pr}
    by_key: dict[str, Task] = {}
    for t in tasks:
        key = by_pr.get(t.pr, f"PR #{t.pr}") if t.pr else t.key
        if key in by_key:
            by_key[key].estimates.extend(t.estimates)
        else:
            by_key[key] = dataclasses.replace(t, key=key, estimates=list(t.estimates))

    universe = set(by_key) | {k for k, w in works.items() if w.is_mine} | set(said)
    outcomes = []
    for key in sorted(universe):
        work = works.get(key)
        extra = (convention.from_commits(work.commits, me) if work else []) + said.get(key, [])
        outcomes.append(evaluate(key, by_key.get(key), work, extra, cfg.calendar, zone, rate))

    result = Analysis(repo.root, cfg, mode, sorted(me), repo.main, outcomes, warnings,
                      points_as_hours=rate, zone=zone)
    _classify(result, repo, me)
    _summarize(result)
    return result


def _classify(a: Analysis, repo: git.Repo, me: set[str]) -> None:
    counted = a.counted
    labelled = {o.key for o in counted if o.task and kinds.from_labels(o.task.labels, o.task.kind_hint)}
    need = [c.sha for o in counted if o.key not in labelled for c in o.work.commits if c.email in me]
    files = git.numstat(repo.root, need) if need else {}
    for o in counted:
        changed = [f for c in o.work.commits if c.email in me for f in files.get(c.sha, [])]
        title = " ".join(filter(None, [o.title, branch_title(o.work.branch)]))
        o.kind = kinds.classify(o.task.labels if o.task else (), o.task.kind_hint if o.task else "", changed, title)


def _summarize(a: Analysis) -> None:
    counted = a.counted
    mode, other = a.mode, ("calendar" if a.mode == "work" else "work")
    a.summary = stats.summarize(o.ratio(mode) for o in counted)
    a.other = stats.summarize(o.ratio(other) for o in counted)
    a.active = stats.summarize(o.ratio("active") for o in counted)

    same: dict[float, list[Outcome]] = {}
    for o in counted:
        same.setdefault(round(o.said_h if mode == "work" else o.said_cal_h, 3), []).append(o)
    common = sorted(same.values(), key=lambda g: (-len(g), g[0].said_h))
    for g in common[:3]:
        if len(g) >= 3:
            text = Counter(o.estimate.parts for o in g).most_common(1)[0][0]
            face = next(o.estimate for o in g if o.estimate.parts == text)
            a.groups.append(Group(face, len(g), stats.multiplier(o.ratio(mode) for o in g)))

    per_kind: dict[str, list[float]] = {}
    for o in counted:
        per_kind.setdefault(o.kind, []).append(o.ratio(mode))
    rows = [(k, stats.multiplier(rs), len(rs)) for k, rs in per_kind.items() if len(rs) >= 5]
    a.kinds = sorted(rows, key=lambda r: r[1]) if len(rows) >= 2 else []
    # Indexed by landing, not by start: indexed by start, the last window would only
    # hold the recent tasks that were quick enough to finish, and fake an improvement.
    a.drift = stats.rolling([(o.end, o.ratio(mode)) for o in counted])
