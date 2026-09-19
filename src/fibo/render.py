"""The output is the product. Far more people will see it in a screenshot than will ever run it."""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from . import stats
from .analysis import Analysis
from .i18n import Lang, by, fmt, times
from .pair import GAP_DAYS, Outcome

SPARK = "▁▂▃▄▅▆▇█"
# The ASCII owl is the source of truth; the pixel owl on the site draws the same faces.
OWL = ("  (o,o)", "  /)_)", '   ""')  # report: the eyes are open
SLEEPY = ("  (-,-)", "  /)_)", '   ""')  # empty: nothing to count yet
MONOCLE = ("  (o,O)", "  /)_)", '   ""')  # doctor: through the monocle
REFUSE = "(ò,ó)"  # every ✗ on stderr


class Style:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.enabled and text else text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def accent(self, text: str) -> str:
        return self._wrap("1;33", text)

    def owl(self, text: str) -> str:
        return self._wrap("38;5;149", text)  # lime

    def bad(self, text: str) -> str:
        return self._wrap("31", text)

    def good(self, text: str) -> str:
        return self._wrap("32", text)


def color_enabled(stream: TextIO, force: bool | None = None) -> bool:
    if force is not None:
        return force
    if os.environ.get("NO_COLOR"):  # https://no-color.org
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        return stream.isatty() and os.environ.get("TERM") != "dumb"
    except (AttributeError, ValueError):
        return False


def pretty_path(path: Path) -> str:
    try:
        return "~/" + path.resolve().relative_to(Path.home().resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


def header(a: Analysis, s: Style, face: tuple[str, str, str] = OWL, tint=None) -> list[str]:
    paint = tint or s.owl
    return [f"{paint(face[0])}   {s.bold('fibo')} · {pretty_path(a.root)}", paint(face[1]), paint(face[2]), ""]


def sizes(a: Analysis) -> tuple[float, float]:
    """How long a day and a week are on the clock in use."""
    if a.mode == "calendar":
        return 24.0, 168.0
    return a.cfg.calendar.hours_per_day, a.cfg.calendar.hours_per_day * a.cfg.calendar.days_per_week


def sparkline(values: list[float], floor: float = math.log(1.1)) -> str:
    logs = [math.log(v) for v in values]
    lo, hi = min(logs), max(logs)
    if hi - lo < floor:  # small wobbles stay small
        mid = (hi + lo) / 2
        lo, hi = mid - floor / 2, mid + floor / 2
    return "".join(SPARK[min(7, max(0, int((x - lo) / (hi - lo) * 8)))] for x in logs)


def months_between(a: datetime, b: datetime) -> int:
    return int((b - a).days / 30.44)


def when(a: Analysis, t: datetime | None) -> str:
    if t is None:
        return "?"
    local = t.astimezone(timezone(a.zone.at(t)))
    z = local.strftime("%z")
    return f"{local:%Y-%m-%d %H:%M} {z[:3]}:{z[3:]}"


def funnel(a: Analysis, lang: Lang) -> str:
    return lang.t("funnel", tasks=lang.count(len(a.outcomes), "task"), closed=lang.int(len(a.closed)),
                  estimated=lang.int(len(a.estimated)), counted=lang.int(len(a.counted)))


def _empty(lang: Lang, s: Style) -> list[str]:
    return [f"  {s.bold(lang.t('empty_title'))}", f"  {lang.t('empty_why')}", "",
            f"  {lang.t('empty_where')}", f"    {lang.t('empty_tracker')}", f"    {lang.t('empty_trailer')}",
            f"    {lang.t('empty_ledger')}", "", f"  {s.dim(lang.t('empty_demo'))}", ""]


def report(a: Analysis, lang: Lang, s: Style, verbose: bool = False) -> str:
    lines = header(a, s, OWL if a.summary else SLEEPY)
    lines += [funnel(a, lang), ""]
    if a.summary is None:
        lines += _empty(lang, s)
    else:
        lines += _body(a, lang, s, verbose)
    excluded = a.excluded
    if excluded:
        n = sum(excluded.values())
        reasons = " · ".join(f"{lang.reason(r)}: {k}" for r, k in excluded.most_common())
        lines.append(lang.t("excluded", n=lang.int(n), tasks=lang.word(n, "task"), reasons=reasons))
    lines.append(s.dim(lang.t("subject", emails=", ".join(a.me) or "?")))
    lines.append(s.dim(lang.t("footer")))
    return "\n".join(lines)


def _body(a: Analysis, lang: Lang, s: Style, verbose: bool) -> list[str]:
    summary, lines = a.summary, []
    day, week = sizes(a)
    rows = []
    for g in a.groups:
        said = g.estimate.work_hours(day, week / day) if a.mode == "work" else g.estimate.calendar_hours()
        rows.append((lang.t("said", said=lang.said(g.estimate.parts, g.estimate.text)),
                     lang.t("took", took=lang.amount(said * g.multiplier, g.estimate.unit, day, week)),
                     by(g.multiplier)))
    if rows:
        w1, w2 = max(len(r[0]) for r in rows), max(len(r[1]) for r in rows)
        lines += [f"  {r[0].ljust(w1)}  — {r[1].ljust(w2)}  {r[2]}" for r in rows] + [""]

    labels = [lang.t("multiplier"), lang.t("p90"), lang.t("under")]
    if verbose:
        labels += [lang.t("geomean"), lang.t("active"), lang.t("idle")]
    width = max(len(x) for x in labels) + 3
    second = ""
    if a.other:
        second = lang.t("calendar_small" if a.mode == "work" else "work_small", x=times(a.other.multiplier))
    lines.append(f"  {labels[0].ljust(width)}{s.accent(times(summary.multiplier))}   {s.dim(second)}".rstrip())
    lines.append(f"  {labels[1].ljust(width)}{times(summary.p90)}")
    lines.append(f"  {labels[2].ljust(width)}{lang.t('under_value', pct=round(summary.under * 100))}")
    if verbose:
        lines.append(f"  {labels[3].ljust(width)}{times(summary.geomean)}")
        if a.active:
            lines.append(f"  {labels[4].ljust(width)}{times(a.active.multiplier)}")
        span = sum(o.span_h for o in a.counted)
        idle = 1 - sum(o.active_h for o in a.counted) / span if span else 0
        lines.append(f"  {labels[5].ljust(width)}{lang.t('idle_value', pct=round(idle * 100))}")
    if summary.n < 10:
        lines.append(s.dim(f"  {lang.t('few', n=summary.n, tasks=lang.word(summary.n, 'task'))}"))
    if a.mode == "calendar":
        lines.append(s.dim(f"  {lang.t('mode_calendar')}"))
    if a.assumed_points:
        lines.append(s.accent(f"  ⚠ {lang.t('points', rate=fmt(a.points_as_hours))}"))

    if a.kinds:
        lines += ["", f"  {lang.t('kinds')}"]
        kw = max(len(lang.kind(k)) for k, _, _ in a.kinds) + 4
        lines += [f"    {lang.kind(k).ljust(kw)}{by(m).ljust(8)}{s.dim(f'n={n}')}" for k, m, n in a.kinds]

    if len(a.drift) >= 2:
        first, last = a.drift[0], a.drift[-1]
        spark = sparkline([m for _, m, _ in a.drift])
        label = lang.t("drift")
        pad = max(8, len(label) + 3)
        line = f"{times(first[1])} {spark} {times(last[1])}"
        now = datetime.now(timezone.utc)
        recent = months_between(last[0], now)  # the last window closes at the last counted start
        left, right = lang.ago(months_between(first[0], now)), lang.ago(recent if recent >= 2 else 0)
        gap = max(2, len(line) - len(left) - len(right))
        lines += ["", f"  {label.ljust(pad)}{line}", " " * (2 + pad) + s.dim(left + " " * gap + right)]
    lines.append("")
    return lines


def _pause(a: Analysis, o: Outcome) -> float:
    if not (o.start and o.end and o.work):
        return 0.0
    events = sorted({o.start, o.end, *(c.at for c in o.work.commits if o.start <= c.at <= o.end)})
    cal = a.cfg.calendar
    return max((cal.work_hours(x, y, a.zone) for x, y in zip(events, events[1:])), default=0.0)


def detail(a: Analysis, o: Outcome, lang: Lang, s: Style) -> str:
    day, week = a.cfg.calendar.hours_per_day, a.cfg.calendar.hours_per_day * a.cfg.calendar.days_per_week
    rows: list[tuple[str, str]] = []
    e = o.estimate
    if e:
        hours = f" = {fmt(o.said_h)}h" if o.said_h and e.unit != "h" else ""
        origin = " · ".join(filter(None, [e.source, e.where, when(a, e.at) if e.at else ""]))
        rows.append((lang.t("d_said"), f"{s.bold(e.text)}{hours} · {origin}"))
        rows += [(lang.t("d_later"), f"{x.text} · {x.source} · {when(a, x.at)}") for x in o.later + o.conflicts]
    if o.start:
        first = o.work.commits[0].short if o.work and o.work.commits and o.start_from == "commit" else ""
        how = lang.t("d_first_commit", sha=first) if first else lang.t("d_tracker")
        rows.append((lang.t("d_started"), f"{when(a, o.start)} · {how}"))
    if o.end:
        sha = o.work.sha[:7] if o.end_from == "merge" and o.work and o.work.sha else ""
        rows.append((lang.t("d_landed" if o.end_from == "merge" else "d_closed"),
                     when(a, o.end) + (f" · {lang.t('d_merge', sha=sha)}" if sha else "")))
    if o.work and o.work.branch:
        rows.append((lang.t("d_branch"), o.work.branch))
    if o.span_h is not None:
        r, ra, rc = o.ratio("work"), o.ratio("active"), o.ratio("calendar")
        rows.append((lang.t("d_span"), f"{fmt(o.span_h)}h · {lang.amount(o.span_h, 'd', day, week)}"
                     + (f"   {s.accent(by(r))}" if r else "")))
        rows.append((lang.t("d_active"), f"{fmt(o.active_h)}h · {lang.amount(o.active_h, 'd', day, week)}"
                     + (f"   {by(ra)}" if ra else "")))
        rows.append((lang.t("d_calendar"), f"{fmt(o.cal_h)}h · {lang.amount(o.cal_h, 'd', 24, 168)}"
                     + (f"   {by(rc)}" if rc else "")))
        pause = _pause(a, o)
        if pause >= day:
            note = f" · {lang.t('d_clipped', days=GAP_DAYS)}" if pause > GAP_DAYS * day else ""
            rows.append((lang.t("d_pause"), lang.amount(pause, "d", day, week) + note))
    if o.work:
        rows.append((lang.t("d_commits"), f"{len(o.work.commits)} · {lang.t('d_yours', n=o.work.mine)}"))
    if o.counted:
        status = s.good(lang.t("s_counted"))
    elif o.status in ("open", "unestimated"):
        status = lang.t(f"s_{o.status}")
    else:
        status = s.bad(f"✗ {lang.reason(o.status)}")
    rows.append((lang.t("d_status"), status))
    if o.task and o.task.url:
        rows.append((lang.t("d_link"), o.task.url))
    width = max(len(k) for k, _ in rows) + 3
    title = f"  {s.bold(o.key)}" + (f" · {o.title}" if o.title else "")
    return "\n".join(header(a, s) + [title, ""] + [f"  {k.ljust(width)}{v}" for k, v in rows]
                     + ["", s.dim(lang.t("footer"))])


def drift(a: Analysis, lang: Lang, s: Style) -> str:
    rows = stats.by_quarter([(o.end, o.ratio(a.mode)) for o in a.counted])
    lines = header(a, s) + [f"  {lang.t('drift_title')}", ""]
    if len(rows) < 2:
        lines.append(f"  {lang.t('drift_empty')}")
    else:
        top = max(math.log(max(m, 1.0001)) for _, _, m, n in rows if n >= 3) if any(r[3] >= 3 for r in rows) else 1
        for y, q, m, n in rows:
            if n < 3:  # one task is not a quarter
                lines.append(s.dim(f"  {y} Q{q}   {times(m).rjust(6)}  {'·'.ljust(24)}  n={n}"))
                continue
            bar = "█" * max(1, round(math.log(max(m, 1.0001)) / top * 24))
            lines.append(f"  {y} Q{q}   {times(m).rjust(6)}  {bar.ljust(24)}  {s.dim(f'n={n}')}")
    lines += ["", s.dim(lang.t("footer"))]
    return "\n".join(lines)
