"""Logarithms, because ratios lie.

took/said is bounded below by zero and unbounded above, so one task at ×40
wrecks an arithmetic mean. In log space ×4 and ×¼ are the same distance from
×1, the median is honest, and exp() brings the answer back to a multiplier.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Sequence


def median(xs: Sequence[float]) -> float:
    s = sorted(xs)
    if not s:
        raise ValueError("median of nothing")
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def quantile(xs: Sequence[float], q: float) -> float:
    """Linear interpolation between closest ranks (the common "type 7")."""
    s = sorted(xs)
    if not s:
        raise ValueError("quantile of nothing")
    pos = (len(s) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def mean(xs: Sequence[float]) -> float:
    if not xs:
        raise ValueError("mean of nothing")
    return sum(xs) / len(xs)


def _logs(ratios: Iterable[float]) -> list[float]:
    return [math.log(r) for r in ratios if r and r > 0]


def multiplier(ratios: Iterable[float]) -> float | None:
    """exp(median(ln r)). The number in the headline."""
    logs = _logs(ratios)
    return math.exp(median(logs)) if logs else None


def geomean(ratios: Iterable[float]) -> float | None:
    logs = _logs(ratios)
    return math.exp(mean(logs)) if logs else None


@dataclass(frozen=True)
class Summary:
    n: int
    multiplier: float  # exp(median(L))
    geomean: float  # exp(mean(L))
    p90: float  # exp(quantile(L, 0.9))
    under: float  # share of tasks with took > said


def summarize(ratios: Iterable[float]) -> Summary | None:
    rs = [r for r in ratios if r and r > 0]
    if not rs:
        return None
    logs = [math.log(r) for r in rs]
    return Summary(
        n=len(rs),
        multiplier=math.exp(median(logs)),
        geomean=math.exp(mean(logs)),
        p90=math.exp(quantile(logs, 0.9)),
        under=sum(r > 1 for r in rs) / len(rs),
    )


def rolling(points: Iterable[tuple[datetime, float]], window: timedelta = timedelta(days=90),
            samples: int | None = None, min_n: int = 3) -> list[tuple[datetime, float, int]]:
    """Rolling median of L over `window`, sampled evenly from the first full window to the end."""
    pts = sorted((t, math.log(r)) for t, r in points if r and r > 0)
    if len(pts) < min_n or pts[-1][0] - pts[0][0] < window:
        return []
    first_full, last = pts[0][0] + window, pts[-1][0]
    count = samples or max(2, min(12, round((last - first_full).days / 45) + 1))
    times = [t for t, _ in pts]
    out = []
    for i in range(count):
        at = first_full + (last - first_full) * (i / (count - 1) if count > 1 else 1)
        lo, hi = bisect.bisect_right(times, at - window), bisect.bisect_right(times, at)
        logs = [l for _, l in pts[lo:hi]]
        if len(logs) >= min_n:
            out.append((at, math.exp(median(logs)), len(logs)))
    return out


def by_quarter(points: Iterable[tuple[datetime, float]]) -> list[tuple[int, int, float, int]]:
    groups: dict[tuple[int, int], list[float]] = {}
    for t, r in points:
        if r and r > 0:
            groups.setdefault((t.year, (t.month - 1) // 3 + 1), []).append(r)
    return [(y, q, multiplier(rs), len(rs)) for (y, q), rs in sorted(groups.items())]
