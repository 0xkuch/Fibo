"""What was said, and when. Plain data and parsing; no I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# A unit said out loud, in calendar hours. Working hours come from the calendar
# (a day is `hours_per_day` long); calendar hours are taken literally.
CALENDAR_HOURS = {"h": 1.0, "d": 24.0, "w": 168.0}

_UNITS = {
    "m": "m", "min": "m", "mins": "m", "minute": "m", "minutes": "m",
    "h": "h", "hr": "h", "hrs": "h", "hour": "h", "hours": "h",
    "d": "d", "day": "d", "days": "d",
    "w": "w", "wk": "w", "wks": "w", "week": "w", "weeks": "w",
}
_PART = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(minutes|minute|mins|min|m|hours|hour|hrs|hr|h|days|day|d|weeks|week|wks|wk|w)(?![a-z])",
    re.IGNORECASE,
)
_POINTS = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:story\s*points?|points?|pts?|sp)$", re.IGNORECASE)
_ORDER = {"h": 0, "d": 1, "w": 2}


@dataclass(frozen=True)
class Estimate:
    """One estimate, exactly as it was written down."""

    text: str  # what was said: "2d", "soon", "3 points"
    source: str  # jira | linear | github | gitlab | convention | ledger
    at: datetime | None  # when it was written down
    parts: tuple[tuple[float, str], ...] = ()  # ((2.0, "d"),) · ((3.0, "pt"),) · () = not a duration
    where: str = ""  # commit, issue URL, ledger line

    @property
    def is_duration(self) -> bool:
        return bool(self.parts) and self.parts[0][1] != "pt"

    @property
    def is_points(self) -> bool:
        return bool(self.parts) and self.parts[0][1] == "pt"

    @property
    def unit(self) -> str | None:
        if not self.parts:
            return None
        if self.is_points:
            return "pt"
        return max((u for _, u in self.parts), key=_ORDER.__getitem__)

    @property
    def points(self) -> float | None:
        return self.parts[0][0] if self.is_points else None

    def work_hours(self, hours_per_day: float = 8.0, days_per_week: float = 5.0,
                   points_as_hours: float | None = None) -> float | None:
        if self.is_points:
            return None if points_as_hours is None else self.parts[0][0] * points_as_hours
        if not self.parts:
            return None
        size = {"h": 1.0, "d": hours_per_day, "w": hours_per_day * days_per_week}
        return sum(n * size[u] for n, u in self.parts)

    def calendar_hours(self, points_as_hours: float | None = None) -> float | None:
        if self.is_points:
            return None if points_as_hours is None else self.parts[0][0] * points_as_hours
        if not self.parts:
            return None
        return sum(n * CALENDAR_HOURS[u] for n, u in self.parts)

    def same_value(self, other: "Estimate") -> bool:
        if self.is_duration and other.is_duration:
            return abs(self.work_hours() - other.work_hours()) < 1e-9
        if self.parts and other.parts:
            return self.parts == other.parts
        return self.text.strip().lower() == other.text.strip().lower()


@dataclass
class Task:
    """A ticket as the tracker remembers it."""

    key: str
    source: str
    title: str = ""
    url: str = ""
    labels: tuple[str, ...] = ()
    kind_hint: str = ""  # issue type, as the tracker names it
    created: datetime | None = None
    started: datetime | None = None  # moved to "In Progress"
    closed: datetime | None = None
    estimates: list[Estimate] = field(default_factory=list)  # every value the field held, oldest first
    pr: str | None = None  # set when the estimate lives in a pull request


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def parse_estimate(text: object, source: str, at: datetime | None = None, where: str = "") -> Estimate:
    """"2d", "4h", "1w", "1.5d", "1d 4h", "3 points" -> Estimate. Anything else is kept, but is not a duration."""
    raw = " ".join(str(text).split())
    body = raw.lstrip("~≈").strip()
    m = _POINTS.match(body)
    if m:
        n = _num(m.group(1))
        return Estimate(raw, source, at, ((n, "pt"),) if n > 0 else (), where)
    parts: list[tuple[float, str]] = []
    for n, u in _PART.findall(body):
        unit = _UNITS[u.lower()]
        parts.append((_num(n) / 60, "h") if unit == "m" else (_num(n), unit))
    rest = _PART.sub(" ", body).replace("+", " ").replace(",", " ").strip()
    if not parts or rest or sum(n for n, _ in parts) <= 0:
        return Estimate(raw, source, at, (), where)
    return Estimate(raw, source, at, tuple(parts), where)


def from_seconds(seconds: object, source: str, at: datetime | None = None, where: str = "",
                 hours_per_day: float = 8.0, days_per_week: float = 5.0) -> Estimate:
    """Trackers store estimates as seconds. Turn them back into what was typed: 57600 -> "2d"."""
    try:
        hours = float(seconds) / 3600  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return Estimate(str(seconds), source, at, (), where)
    if hours <= 0:
        return Estimate(f"{seconds}s", source, at, (), where)
    week = hours_per_day * days_per_week
    w, rest = divmod(hours, week)
    d, h = divmod(rest, hours_per_day)
    parts = tuple((round(n, 4), u) for n, u in ((w, "w"), (d, "d"), (h, "h")) if round(n, 4))
    text = " ".join(f"{n:g}{u}" for n, u in parts)
    return Estimate(text, source, at, parts, where)


_TS = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2})?)(\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?$", re.IGNORECASE
)


def parse_time(value: object) -> datetime | None:
    """ISO 8601 as trackers actually send it: "Z", "+0300", "+03:00", milliseconds or not."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    m = _TS.match(str(value).strip())
    if not m:
        return None
    day, clock, frac, tz = m.groups()
    dt = datetime.fromisoformat(f"{day}T{clock}")
    if frac:
        dt = dt.replace(microsecond=int(frac[1:7].ljust(6, "0")))
    if not tz or tz.upper() == "Z":
        return dt.replace(tzinfo=timezone.utc)
    sign = -1 if tz[0] == "-" else 1
    offset = timedelta(hours=int(tz[1:3]), minutes=int(tz[-2:]))
    return dt.replace(tzinfo=timezone(sign * offset))
