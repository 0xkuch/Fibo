"""Task ↔ branch ↔ merge. Everything else is meaningless without this.

A task's work is found in history, not typed in:
  * a merge on the main line brings in a branch — its commits are the work,
    the branch name (or the commits) carry the task key;
  * commits that landed straight on main (rebase, squash) carry the key in
    their message;
  * a branch that was never merged is still work, just unfinished.
Start is the first commit, end is the landing. Nothing is guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from .clock import Calendar, Zone, calendar_hours
from .git import Commit, Repo, mainline
from .model import Estimate, Task

GAP_DAYS = 3  # longer pauses are clipped in `active`, and break a chain of follow-up PRs
MIN_HOURS = 0.25  # the clock's resolution: nothing takes less than fifteen minutes
PRIORITY = ("jira", "linear", "github", "gitlab", "convention", "ledger")
MAINLINES = {"main", "master", "trunk", "develop", "development", "dev"}

# Prefixes that look like keys and are not: UTF-8, ISO-8601, SHA-256, RFC-2119...
BLOCKLIST = frozenset({
    "UTF", "ISO", "SHA", "RFC", "CVE", "PEP", "HTTP", "HTTPS", "TLS", "SSL", "AES", "RSA", "MD",
    "ES", "IE", "WIN", "GPL", "LGPL", "ECMA", "IPV", "SMTP", "COVID", "UTC", "GMT", "CP", "KOI",
})
_UPPER = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{1,9})-(\d{1,7})(?!\d)")
_ANY = re.compile(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{1,9})([-_])(\d{1,7})(?!\d)")
_NUM_BRANCH = re.compile(r"(?:^|/)(?:issues?[-_/]?|gh[-_]?)?(\d{1,7})(?=[-_/]|$)", re.IGNORECASE)
_NUM_TEXT = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?|see|issue|towards)\s*:?\s*#(\d{1,7})\b",
                       re.IGNORECASE)
_SQUASH_PR = re.compile(r"\(#(\d+)\)\s*$")


class Keys:
    """Finds task keys in branch names and commit messages."""

    def __init__(self, known: Iterable[str] = (), numeric: bool = False):
        self.known = {k.upper() for k in known}
        self.numeric = numeric

    def in_branch(self, name: str) -> list[str]:
        out: list[str] = []
        for m in _ANY.finditer(name):
            prefix, sep, number = m.groups()
            key = f"{prefix.upper()}-{int(number)}"
            as_written = prefix.isupper() and sep == "-" and prefix not in BLOCKLIST
            if key in self.known or as_written:
                out.append(key)
        if self.numeric:
            out += [f"#{int(m.group(1))}" for m in _NUM_BRANCH.finditer(name) if f"#{int(m.group(1))}" in self.known]
        return list(dict.fromkeys(out))

    def in_text(self, text: str) -> list[str]:
        out = [f"{m.group(1)}-{int(m.group(2))}" for m in _UPPER.finditer(text) if m.group(1) not in BLOCKLIST]
        if self.known:
            for m in _ANY.finditer(text):
                key = f"{m.group(1).upper()}-{int(m.group(3))}"
                if key in self.known:
                    out.append(key)
        if self.numeric:
            out += [f"#{int(m.group(1))}" for m in _NUM_TEXT.finditer(text) if f"#{int(m.group(1))}" in self.known]
        return list(dict.fromkeys(out))


def parse_merge(subject: str) -> tuple[str | None, str | None]:
    """Merge commit subject -> (branch, pull request number). GitHub, GitLab, Bitbucket, Azure, plain git."""
    m = re.match(r"^Merge pull request #(\d+) from (\S+)", subject)
    if m:
        ref = m.group(2)
        return (ref.split("/", 1)[1] if "/" in ref else ref), m.group(1)
    m = re.match(r"^Merged in (\S+) \(pull request #(\d+)\)", subject)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"^Merge remote-tracking branch '([^']+)'", subject)
    if m:
        ref = m.group(1)
        return (ref.split("/", 1)[1] if "/" in ref else ref), None
    m = re.match(r"^Merge branch '([^']+)'", subject)
    if m:
        return m.group(1), None
    m = re.match(r"^Merged PR (\d+):", subject)
    if m:
        return None, m.group(1)
    return None, None


_KEY_PREFIX = re.compile(r"^\s*\[?[A-Za-z][A-Za-z0-9]{1,9}-\d+\]?[\s:/-]*")


def commit_title(c: Commit) -> str:
    """"PROJ-412: fix auth refresh (#12)" -> "fix auth refresh"."""
    return _KEY_PREFIX.sub("", _SQUASH_PR.sub("", c.subject)).strip()


def branch_title(branch: str | None) -> str:
    """"feature/PROJ-412-fix-auth-refresh" -> "fix auth refresh"."""
    if not branch:
        return ""
    last = branch.rsplit("/", 1)[-1]
    last = _ANY.sub(" ", last)
    return " ".join(w for w in re.split(r"[-_\s]+", last) if w and not w.isdigit())


@dataclass
class Unit:
    """One landing: a merge, a run of commits straight on main, or a branch still out there."""

    how: str  # "merge" | "direct" | "branch"
    commits: list[Commit]  # non-merge, oldest first
    landed: datetime | None  # when it reached main; None while unmerged
    sha: str | None = None
    branch: str | None = None
    pr: str | None = None
    title: str = ""
    squashed: bool = False  # one commit dated at its landing: history cannot say when work began

    @property
    def start(self) -> datetime | None:
        return None if self.squashed or not self.commits else self.commits[0].at


def _walk(commits: dict[str, Commit], tip: str, stop: set[str], mark: set[str]) -> list[str]:
    """Commits reachable from `tip` and not in `stop`. Adds what it finds to `mark`."""
    out, stack = [], [tip]
    while stack:
        sha = stack.pop()
        if sha in stop or sha in mark or sha not in commits:
            continue
        mark.add(sha)
        out.append(sha)
        stack.extend(commits[sha].parents)
    return out


def _split(own: list[Commit], branch: str | None, keys: Keys, context: str) -> dict[str, list[Commit]]:
    if branch and branch not in MAINLINES:
        found = keys.in_branch(branch)
        if found:
            return {found[0]: own}
    per: dict[str, list[Commit]] = {}
    loose: list[Commit] = []
    for c in own:
        found = keys.in_text(c.message)
        (per.setdefault(found[0], []) if found else loose).append(c)
    if not per:
        found = keys.in_text(context)
        if found:
            return {found[0]: own}
        return {branch: own} if branch and branch not in MAINLINES else {}
    if loose and branch not in MAINLINES:
        biggest = max(per, key=lambda k: len(per[k]))
        per[biggest] = sorted(per[biggest] + loose, key=lambda c: c.at)
    return per


def collect(repo: Repo, keys: Keys, remotes: Iterable[str] = ("origin",)) -> dict[str, list[Unit]]:
    """Every landing in history, grouped by task key. One pass over the main line."""
    commits = repo.commits
    found: dict[str, list[Unit]] = {}
    seen: set[str] = set()  # everything reachable from main so far; always closed under ancestry
    run: tuple[str, Unit] | None = None  # consecutive direct commits for one key

    for sha in mainline(commits, repo.tip):
        c = commits[sha]
        if c.is_merge:
            run = None
            introduced: list[str] = []
            for parent in c.parents[1:]:
                introduced += _walk(commits, parent, set(), seen)
            seen.add(sha)
            branch, pr = parse_merge(c.subject)
            own = sorted((commits[x] for x in introduced if not commits[x].is_merge), key=lambda k: k.at)
            if not own:
                continue
            title = c.body.splitlines()[0].strip() if c.body else ""  # GitHub puts the PR title here
            for key, part in _split(own, branch, keys, c.message).items():
                found.setdefault(key, []).append(Unit("merge", part, c.landed, sha, branch, pr,
                                                      title or commit_title(part[0]) or branch_title(branch)))
            continue
        seen.add(sha)
        pr_match = _SQUASH_PR.search(c.subject)
        pr = pr_match.group(1) if pr_match else None
        in_msg = keys.in_text(c.message)
        key = in_msg[0] if in_msg else (f"PR #{pr}" if pr else None)
        if key is None:
            run = None
            continue
        title = commit_title(c)
        if run and run[0] == key:
            run[1].commits.append(c)
            run[1].landed, run[1].sha, run[1].squashed = c.landed, sha, False
            continue
        squashed = abs((c.landed - c.at).total_seconds()) < 120
        unit = Unit("direct", [c], c.landed, sha, None, pr, title, squashed)
        found.setdefault(key, []).append(unit)
        run = (key, unit)

    # Branches that never reached main: unfinished work, or the leftovers of a squash.
    prefixes = tuple(f"{r}/" for r in remotes)
    tips_done: set[str] = set()
    for name, tip in sorted(repo.refs.items()):
        if name == repo.main or tip in tips_done or tip in seen:
            continue
        tips_done.add(tip)
        branch = name[len(next(p for p in prefixes if name.startswith(p))):] if name.startswith(prefixes) else name
        if branch in MAINLINES:
            continue
        own = sorted((commits[x] for x in _walk(commits, tip, seen, set()) if not commits[x].is_merge),
                     key=lambda k: k.at)
        if not own:
            continue
        for key, part in _split(own, branch, keys, "").items():
            units = found.setdefault(key, [])
            shas = {x.sha for x in part}
            if any(u.how == "branch" and shas <= {x.sha for x in u.commits} for u in units):
                continue
            units.append(Unit("branch", part, None, tip, branch, None,
                              commit_title(part[0]) or branch_title(branch)))
    return found


@dataclass
class Work:
    """What history says about one task."""

    key: str
    units: list[Unit]
    start: datetime | None  # first commit; None when history cannot say
    end: datetime | None  # last landing of the chain; None if it never landed
    commits: list[Commit]
    mine: int
    branch: str | None = None
    pr: str | None = None
    sha: str | None = None
    title: str = ""

    @property
    def is_mine(self) -> bool:
        """Mostly your commits. A task you touched once in passing is not yours."""
        return self.mine > 0 and self.mine * 2 >= len(self.commits)


def work_for(key: str, units: list[Unit], me: set[str], cal: Calendar, zone: Zone) -> Work:
    landed = sorted((u for u in units if u.landed), key=lambda u: u.landed)
    loose = [u for u in units if not u.landed]
    end = None
    if landed:
        # The first landing, plus follow-ups that started within GAP_DAYS of the
        # previous landing. A "fix PROJ-412 again" three months later is new work.
        chain, end = [landed[0]], landed[0].landed
        for u in landed[1:]:
            s = u.start
            if s is not None and cal.work_hours(end, s, zone) <= GAP_DAYS * cal.hours_per_day:
                chain.append(u)
                end = max(end, u.landed)
    else:
        chain = loose
    starts = [u.start for u in chain if u.start]
    start = min(starts) if starts else None
    if start is None and landed:
        # Squashed on landing; the branch it came from may still be around.
        leftovers = [u for u in loose if u.start and u.start <= end]
        if leftovers:
            start = min(u.start for u in leftovers)
            chain = chain + leftovers
    commits = sorted({c.sha: c for u in chain for c in u.commits}.values(), key=lambda c: c.at)
    first = next((u for u in chain if u.branch), chain[0] if chain else None)
    last_landed = max((u for u in chain if u.landed), key=lambda u: u.landed, default=None)
    return Work(
        key=key, units=chain, start=start, end=end, commits=commits,
        mine=sum(c.email in me for c in commits),
        branch=first.branch if first else None,
        pr=next((u.pr for u in chain if u.pr), None),
        sha=last_landed.sha if last_landed else None,
        title=next((u.title for u in chain if u.title), ""),
    )


@dataclass
class Outcome:
    key: str
    title: str = ""
    status: str = "open"  # counted · open · unestimated · not_duration · points · no_branch · not_yours · after_start
    closed: bool = False
    task: Task | None = None
    work: Work | None = None
    estimate: Estimate | None = None
    later: list[Estimate] = field(default_factory=list)  # other values written after work began
    conflicts: list[Estimate] = field(default_factory=list)  # disagreeing values from other places
    start: datetime | None = None
    end: datetime | None = None
    start_from: str = ""  # commit | tracker
    end_from: str = ""  # merge | tracker
    said_h: float | None = None  # working hours
    said_cal_h: float | None = None  # calendar hours, words taken literally
    span_h: float | None = None
    active_h: float | None = None
    cal_h: float | None = None
    kind: str = "other"

    @property
    def counted(self) -> bool:
        return self.status == "counted"

    def ratio(self, mode: str = "work") -> float | None:
        if mode == "calendar":
            return self.cal_h / self.said_cal_h if self.cal_h and self.said_cal_h else None
        if mode == "active":
            return self.active_h / self.said_h if self.active_h and self.said_h else None
        return self.span_h / self.said_h if self.span_h and self.said_h else None


def _when(e: Estimate) -> float:
    return e.at.timestamp() if e.at else float("inf")


def choose(estimates: list[Estimate], start: datetime | None) -> tuple[Estimate | None, list[Estimate], list[Estimate]]:
    """The estimate that stood when work began, values written after that, disagreeing values elsewhere."""
    if not estimates:
        return None, [], []
    primary = next(s for s in PRIORITY + tuple({e.source for e in estimates}) if any(e.source == s for e in estimates))
    events = sorted((e for e in estimates if e.source == primary), key=_when)
    before = [e for e in events if start is not None and e.at is not None and e.at <= start]
    chosen = before[-1] if before else events[0]
    later = [e for e in events if e.at and start and e.at > start and not e.same_value(chosen)]
    others = [e for e in estimates if e.source != primary]
    conflicts = [e for e in others if not e.same_value(chosen)]
    return chosen, later, conflicts


def _took(work_h: float, cal_h: float, cal: Calendar) -> float:
    if work_h >= MIN_HOURS:
        return work_h
    if work_h == 0 and cal_h > 0:  # done entirely outside the calendar: a weekend, a night
        return max(MIN_HOURS, min(cal_h, cal.hours_per_day))
    return MIN_HOURS


def evaluate(key: str, task: Task | None, work: Work | None, extra: list[Estimate], cal: Calendar,
             zone: Zone, points_as_hours: float | None = None) -> Outcome:
    o = Outcome(key, task=task, work=work)
    o.title = (task.title if task and task.title else "") or (work.title if work else "")
    git_end = work.end if work else None
    o.closed = git_end is not None or (task is not None and task.closed is not None)
    if work and work.start:
        o.start, o.start_from = work.start, "commit"
    elif work and task and task.started:
        o.start, o.start_from = task.started, "tracker"
    if git_end:
        o.end, o.end_from = git_end, "merge"
    elif task and task.closed:
        o.end, o.end_from = task.closed, "tracker"

    o.estimate, o.later, o.conflicts = choose(list(task.estimates if task else []) + list(extra), o.start)
    e = o.estimate
    if e is not None:
        o.said_h = e.work_hours(cal.hours_per_day, cal.days_per_week, points_as_hours)
        o.said_cal_h = e.calendar_hours(points_as_hours)
    if o.start and o.end:
        o.cal_h = max(calendar_hours(o.start, o.end), MIN_HOURS)
        o.span_h = _took(cal.work_hours(o.start, o.end, zone), o.cal_h, cal)
        events = sorted({o.start, o.end, *(c.at for c in (work.commits if work else []) if o.start <= c.at <= o.end)})
        cap = GAP_DAYS * cal.hours_per_day
        active = sum(min(cal.work_hours(a, b, zone), cap) for a, b in zip(events, events[1:]))
        o.active_h = min(o.span_h, _took(active, o.cal_h, cal))

    if not o.closed:
        o.status = "open"
    elif e is None:
        o.status = "unestimated"
    elif e.is_points and points_as_hours is None:
        o.status = "points"
    elif not (e.is_duration or e.is_points) or not o.said_h or o.said_h <= 0:
        o.status = "not_duration"
    elif work is None or o.start is None:
        o.status = "no_branch"
    elif work.mine == 0:
        o.status = "not_yours"
    elif e.at is None or e.at > o.start:
        o.status = "after_start"
    else:
        o.status = "counted"
    return o
