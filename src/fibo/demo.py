"""`fibo demo`: two years of somebody's promises, then the report.

Reproducible: a fixed seed, shifted to end this week in whole weeks, so the
weekdays line up and the numbers never change. It is nobody's real history.
Built with one `git fast-import`, so it takes a second, not a minute.
"""

from __future__ import annotations

import math
import os
import random
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from . import config, git, render
from .analysis import analyze
from .clock import Calendar
from .sources import ledger

ME = ("You", "you@fibo.demo")
SAM = ("Sam Okafor", "sam@fibo.demo")
MARKER = ".fibo-demo"
SEED, WEEKS = 3, 104
CAL = Calendar()
HOME, AWAY = timedelta(hours=3), timedelta(hours=1)

#             share  median×  sigma  what gets said
KINDS = {
    "bugfix": (0.27, 1.35, 0.60, ["1h", "2h", "4h", "4h", "1d", "1d", "2d"]),
    "feature": (0.40, 3.7, 0.50, ["1d", "2d", "2d", "2d", "3d", "1w", "1w"]),
    "refactor": (0.19, 6.0, 0.50, ["4h", "1d", "2d", "2d", "3d"]),
    "migration": (0.14, 7.4, 0.45, ["1h", "2h", "4h", "1d", "1d", "2d"]),
}
DRIFT = (0.95, 0.06)  # the multiplier creeps up by 6% over the two years; nobody gets better
HOURS = {"h": 1, "d": 8, "w": 40}
THINGS = ["auth token refresh", "invoice export", "search indexing", "rate limiter", "webhook retries",
          "session cache", "billing proration", "email digests", "audit log", "user avatars", "csv import",
          "timezone handling", "password reset", "feature flags", "report builder", "notification settings",
          "api pagination", "file uploads", "sso login", "order history"]
BUGS = ["race", "crash on empty input", "off-by-one", "memory leak", "wrong totals", "double submit",
        "stale cache", "timeout", "encoding error", "flaky retry"]
TABLES = ["orders", "users", "invoices", "events", "sessions", "payments", "accounts", "audit_log"]
TITLES = {
    "bugfix": ["fix {thing} {bug}", "fix {bug} in {thing}", "hotfix {thing} {bug}"],
    "feature": ["add {thing}", "implement {thing} v2", "support bulk {thing}", "add {thing} to admin"],
    "refactor": ["refactor {thing}", "extract {thing} service", "clean up {thing} module", "rewrite {thing} client"],
    "migration": ["migrate {table} to partitioned table", "migrate {table} ids to uuid",
                  "migrate {table} to new schema", "migrate {table} off legacy storage"],
}
FOLLOWUPS = ["address review", "tests", "handle empty input", "fix lint", "rename per review", "more tests",
             "edge case", "wip", "docs", "simplify"]
VAGUE = ["soon", "end of sprint", "small", "quick win"]
POINTS = ["3 points", "5sp", "2 pts"]


@dataclass
class Plan:
    who: tuple[str, str]
    kind: str
    title: str
    said: str
    start: datetime
    land: datetime | None
    offset: timedelta
    times: list[datetime]
    mode: str = "ok"
    key: str = ""
    branch: str = ""
    commits: list[tuple[datetime, str, dict[str, str], tuple[str, str]]] = field(default_factory=list)
    final: dict[str, str] = field(default_factory=dict)


def _hours(said: str) -> int:
    return int(said[:-1]) * HOURS[said[-1]]


def _trailer(rng: random.Random, said: str) -> str:
    return rng.choice(["Estimate: {}", "Estimate: {}", "Est: {}", "/estimate {}"]).format(said)


def _timeline(rng: random.Random, who: tuple[str, str], density: float, start: datetime, end: datetime) -> list[Plan]:
    plans: list[Plan] = []
    t = CAL.advance(start + timedelta(days=rng.randint(0, 4)), rng.uniform(0, 6), HOME)
    while t < end:
        progress = (t - start) / (end - start)
        offset = AWAY if who == ME and 0.56 < progress < 0.66 else HOME
        kind = rng.choices(list(KINDS), [k[0] for k in KINDS.values()])[0]
        _, median, sigma, offers = KINDS[kind]
        said = rng.choice(offers)
        ratio = math.exp(rng.gauss(math.log(median * (DRIFT[0] + DRIFT[1] * progress)), sigma))
        took = min(_hours(said) * ratio, 320.0)
        count = max(1, min(9, 1 + round(took / 7)))
        fracs = sorted(rng.uniform(0.05, 0.97) for _ in range(count - 1))
        times = [t] + [CAL.advance(t, took * f, offset) for f in fracs]
        land = CAL.advance(t, took, offset)
        title = rng.choice(TITLES[kind]).format(thing=rng.choice(THINGS), bug=rng.choice(BUGS),
                                               table=rng.choice(TABLES))
        plan = Plan(who, kind, title, said, t, land if land < end else None, offset, times)
        roll = rng.random()
        if plan.land is None:
            plan.mode = "open"
        elif who == SAM:
            plan.mode = "ok" if roll > 0.3 else "none"
        else:
            plan.mode = next(m for limit, m in ((0.065, "late"), (0.09, "vague"), (0.105, "points"),
                                                (0.20, "none"), (0.215, "squash"), (0.228, "conflict"),
                                                (1.01, "ok")) if roll < limit)
        if plan.mode in ("late", "conflict") and len(times) < 2:
            plan.times.append(CAL.advance(t, took * 0.5, offset))
        plans.append(plan)
        t = CAL.advance(t, took * rng.uniform(0.15, 0.45) / density, offset)
    return plans


def _fill(rng: random.Random, p: Plan, number: int) -> None:
    """Keys, branch names, commit messages and files for one plan."""
    p.key = f"PROJ-{number}"
    slug = "-".join(p.title.replace("_", "-").split()[:5])
    prefix = {"bugfix": "bugfix/", "feature": "feature/"}.get(p.kind, "") if rng.random() < 0.4 else ""
    p.branch = f"{prefix}{p.key}-{slug}"
    name = p.key.lower().replace("-", "_")
    module = rng.choice(THINGS).replace(" ", "_")
    paths = {"bugfix": [f"src/{module}/{name}.py", f"tests/test_{name}.py"],
             "feature": [f"src/{module}/{name}.py", f"api/{name}.py"],
             "refactor": [f"src/{module}/{name}.py", f"src/{module}/{name}_helpers.py"],
             "migration": [f"migrations/{number:04d}_{name}.py", f"src/{module}/{name}_models.py"]}[p.kind]
    other = SAM if p.who == ME else ME
    helper = rng.randrange(1, len(p.times)) if len(p.times) > 2 and rng.random() < 0.08 else -1
    for i, at in enumerate(sorted(p.times)):
        if i == 0:
            message = f"{p.key} {p.title}"
            if p.mode in ("ok", "conflict", "open", "squash"):
                message += "\n\n" + _trailer(rng, p.said)
            elif p.mode == "vague":
                message += f"\n\nEstimate: {rng.choice(VAGUE)}"
            elif p.mode == "points":
                message += f"\n\nEst: {rng.choice(POINTS)}"
        else:
            message = rng.choice(FOLLOWUPS)
            if (p.mode == "late" and i == 1) or (p.mode == "conflict" and i == len(p.times) - 1):
                said = p.said if p.mode == "late" else f"{int(p.said[:-1]) * 2}{p.said[-1]}"
                message += "\n\n" + _trailer(rng, said)
        changes = {}
        for path in paths if i == 0 else [paths[0] if rng.random() < 0.75 else paths[1]]:
            primary = path == paths[0]  # most of the diff goes where the work is
            lines = rng.randint(40, 90) if primary and p.kind == "migration" and i == 0 else \
                rng.randint(3, 12) if primary else rng.randint(1, 5)
            body = "".join(f"value_{i}_{k} = {rng.randint(0, 999)}\n" for k in range(lines))
            p.final[path] = p.final.get(path, f"# {p.key} {p.title}\n") + body
            changes[path] = p.final[path]
        p.commits.append((at, message, changes, other if i == helper else p.who))


class Stream:
    """A `git fast-import` stream: every commit, with exact dates, in one process."""

    def __init__(self) -> None:
        self.out = bytearray()
        self.marks = 0

    def _data(self, text: str) -> None:
        raw = text.encode("utf-8")
        self.out += b"data %d\n" % len(raw) + raw + b"\n"

    @staticmethod
    def _stamp(at: datetime) -> str:
        minutes = int(at.utcoffset().total_seconds() // 60)
        return f"{int(at.timestamp())} {'+' if minutes >= 0 else '-'}{abs(minutes) // 60:02d}{abs(minutes) % 60:02d}"

    def commit(self, ref: str, who: tuple[str, str], at: datetime, message: str, parents: list[int],
               files: dict[str, str], landed: datetime | None = None) -> int:
        """`at` is the author date; `landed` the committer date, when a rebase moved it later."""
        self.marks += 1
        author = f"{who[0]} <{who[1]}> {self._stamp(at)}"
        committer = f"{who[0]} <{who[1]}> {self._stamp(landed or at)}"
        self.out += f"commit {ref}\nmark :{self.marks}\nauthor {author}\ncommitter {committer}\n".encode()
        self._data(message)
        if parents:
            self.out += f"from :{parents[0]}\n".encode() + b"".join(f"merge :{p}\n".encode() for p in parents[1:])
        for path, content in files.items():
            self.out += f"M 100644 inline {path}\n".encode()
            self._data(content)
        self.out += b"\n"
        return self.marks


def _end_of_history() -> datetime:
    """This week's Monday, 00:00 at +03:00. History ends there, in whole weeks."""
    now = datetime.now(timezone(HOME))
    monday = (now - timedelta(days=now.weekday())).date()
    return datetime.combine(monday, time(), tzinfo=timezone(HOME))


def build(path: Path, seed: int = SEED) -> list[Plan]:
    rng = random.Random(seed)
    end = _end_of_history()
    start = end - timedelta(weeks=WEEKS)
    plans = sorted(_timeline(rng, ME, 1.0, start, end) + _timeline(rng, SAM, 0.45, start, end),
                   key=lambda p: p.start)
    for number, p in enumerate(plans, 101):
        _fill(rng, p, number)

    path.mkdir(parents=True, exist_ok=True)
    git.run(["init", "-q"], path)
    stream = Stream()
    readme = "# acme-backend\n\nA demo repository generated by `fibo demo`. Nobody's real history.\n"
    main = stream.commit("refs/heads/main", ME, start - timedelta(days=3), "initial commit", [], {
        "README.md": readme, "src/__init__.py": "", MARKER: "generated by fibo demo\n",
        ".fibo.json": '{\n  "emails": ["you@fibo.demo"]\n}\n'})
    events = [(p.start, 0, i) for i, p in enumerate(plans) if p.mode != "squash"]
    events += [(p.land, 1, i) for i, p in enumerate(plans) if p.land]
    tips: dict[int, int] = {}
    merged: list[str] = []
    for number, (_, what, i) in enumerate(sorted(events, key=lambda e: (e[0], e[1])), 1):
        p = plans[i]
        if what == 0:
            tip = main
            for at, message, files, who in p.commits:
                tip = stream.commit(f"refs/heads/{p.branch}", who, at, message, [tip], files)
            tips[i] = tip
        elif p.mode == "squash":
            message = f"{p.key} {p.title} (#{number})\n\n{p.commits[0][1].split(chr(10) * 2)[-1]}"
            main = stream.commit("refs/heads/main", p.who, p.land, message, [main], p.final)
        else:
            user = "you" if p.who == ME else "sam"
            message = f"Merge pull request #{number} from {user}/{p.branch}\n\n{p.title}"
            main = stream.commit("refs/heads/main", p.who, p.land, message, [main, tips[i]], p.final)
            merged.append(p.branch)
    stream.out += b"done\n"
    proc = subprocess.run(["git", "fast-import", "--quiet", "--done"], cwd=path, input=bytes(stream.out),
                          capture_output=True)
    if proc.returncode:
        raise git.GitError(proc.stderr.decode("utf-8", "replace"))
    git.run(["update-ref", "--stdin"], path, stdin="".join(f"delete refs/heads/{b}\n" for b in merged))
    git.run(["symbolic-ref", "HEAD", "refs/heads/main"], path)
    git.run(["reset", "-q", "--hard"], path)
    git.run(["config", "user.email", ME[1]], path)
    git.run(["config", "user.name", ME[0]], path)
    for n, said in ((len(plans) + 101, "2d"), (len(plans) + 102, "1w")):
        ledger.append(path, f"PROJ-{n}", said, ME[1], end - timedelta(days=3, hours=-11))
    return plans


def _remove(path: Path) -> None:
    def retry(func, target, *_):
        os.chmod(target, stat.S_IWRITE)  # git makes its objects read-only; Windows minds
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


def run(args, lang, s) -> int:
    target = (Path(args.args[0]).expanduser() if args.args else Path(tempfile.gettempdir()) / "fibo-demo").resolve()
    if target.exists():
        if (target / MARKER).is_file():
            _remove(target)
        elif target.is_file() or any(target.iterdir()):
            print(lang.t("demo_exists", path=target), file=sys.stderr)
            return 2
    build(target)
    cfg = config.load(target, git.user_email(target))
    a = analyze(target, cfg, mode="calendar" if args.calendar else "work", points_as_hours=args.points_as_hours)
    print(render.report(a, lang, s, args.verbose))
    print()
    where = f'"{target}"' if " " in str(target) else str(target)
    example = max((o for o in a.counted if o.kind == "migration"), key=lambda o: o.ratio(), default=None)
    print(s.dim(lang.t("demo_where", path=target)))
    print(s.dim(lang.t("demo_note")))
    for cmd in ([example.key] if example else []) + ["drift", "doctor"]:
        print(s.dim(lang.t("demo_next", path=where, cmd=cmd)))
    return 0
