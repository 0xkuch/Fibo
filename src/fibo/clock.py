"""Working hours between two instants, in the author's own time zone.

Estimates are made in ideal time ("two days of work"); history happens in
calendar time. The clock converts one into the other: Mon–Fri, 9:00–18:00
local, eight working hours to the day. "Local" is the offset the author's own
commits carried at that moment, so moving from +03:00 to +01:00 moves the day.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Iterable, Iterator

UTC = timezone.utc


@dataclass(frozen=True)
class Calendar:
    workdays: frozenset = frozenset({0, 1, 2, 3, 4})
    day_start: float = 9.0
    day_end: float = 18.0
    hours_per_day: float = 8.0

    @property
    def days_per_week(self) -> float:
        return float(len(self.workdays)) or 5.0

    @property
    def window(self) -> float:
        return self.day_end - self.day_start

    def unit_hours(self, unit: str) -> float:
        return {"h": 1.0, "d": self.hours_per_day, "w": self.hours_per_day * self.days_per_week}[unit]

    def work_hours(self, a: datetime | None, b: datetime | None, zone: "Zone | None" = None) -> float:
        """Working hours in [a, b]. The 9-hour window counts as `hours_per_day`."""
        if a is None or b is None or b <= a:
            return 0.0
        zone = zone or Zone()
        seconds = 0.0
        for s, e, offset in zone.segments(a, b):
            seconds += self._window_seconds(_local(s, offset), _local(e, offset))
        return seconds / 3600 * self.hours_per_day / self.window

    def _window_seconds(self, lo: datetime, hi: datetime) -> float:
        start, end = timedelta(hours=self.day_start), timedelta(hours=self.day_end)
        total, day = 0.0, lo.date()
        while day <= hi.date():
            if day.weekday() in self.workdays:
                base = datetime.combine(day, time())
                s, e = max(base + start, lo), min(base + end, hi)
                if e > s:
                    total += (e - s).total_seconds()
            day += timedelta(days=1)
        return total

    def advance(self, a: datetime, hours: float, offset: timedelta) -> datetime:
        """The instant `hours` of working time after `a`. Inverse of work_hours; the demo needs it."""
        need = hours * self.window / self.hours_per_day * 3600
        start, end = timedelta(hours=self.day_start), timedelta(hours=self.day_end)
        local = _local(a, offset)
        while True:
            base = datetime.combine(local.date(), time())
            if local.weekday() in self.workdays:
                s, e = max(base + start, local), base + end
                if e > s:
                    have = (e - s).total_seconds()
                    if have >= need:
                        return (s + timedelta(seconds=need)).replace(tzinfo=timezone(offset))
                    need -= have
            local = base + timedelta(days=1)


def calendar_hours(a: datetime | None, b: datetime | None) -> float:
    if a is None or b is None:
        return 0.0
    return max(0.0, (b - a).total_seconds() / 3600)


def _local(t: datetime, offset: timedelta) -> datetime:
    return (t.astimezone(UTC) + offset).replace(tzinfo=None)


class Zone:
    """The author's UTC offset over time, read from their own commits."""

    def __init__(self, samples: Iterable[tuple[datetime, timedelta]] = ()):
        runs: list[list] = []  # [offset, first seen, commits]
        for t, offset in sorted(samples, key=lambda s: s[0]):
            if runs and runs[-1][0] == offset:
                runs[-1][2] += 1
            else:
                runs.append([offset, t, 1])
        kept: list[list] = []
        for i, run in enumerate(runs):
            # One commit in another zone between two identical ones is a web-UI
            # edit or a CI box, not a move.
            if run[2] == 1 and 0 < i < len(runs) - 1 and runs[i - 1][0] == runs[i + 1][0]:
                continue
            if kept and kept[-1][0] == run[0]:
                continue
            kept.append(run)
        self._times = [r[1] for r in kept]
        self._offsets = [r[0] for r in kept]

    @classmethod
    def fixed(cls, offset: timedelta) -> "Zone":
        return cls([(datetime(1970, 1, 1, tzinfo=UTC), offset)])

    @property
    def offsets(self) -> list[timedelta]:
        return list(self._offsets)

    def at(self, t: datetime) -> timedelta:
        if not self._offsets:
            return t.utcoffset() or timedelta(0)
        i = bisect.bisect_right(self._times, t) - 1
        return self._offsets[max(i, 0)]

    def segments(self, a: datetime, b: datetime) -> Iterator[tuple[datetime, datetime, timedelta]]:
        cuts = [c for c in self._times[1:] if a < c < b]
        edges = [a, *cuts, b]
        for s, e in zip(edges, edges[1:]):
            yield s, e, self.at(s)
