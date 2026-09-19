"""`.fibo.json`: who you are and where your estimates live.

The loader reads exactly one file. Secrets come from that file or from an
environment variable named in it — never from a path, never from a key file.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .clock import Calendar

CONFIG_NAME = ".fibo.json"
TRACKERS = ("jira", "linear", "github", "gitlab")
TOKEN_ENV = {"jira": "JIRA_API_TOKEN", "linear": "LINEAR_API_KEY", "github": "GITHUB_TOKEN", "gitlab": "GITLAB_TOKEN"}
KNOWN = {"$schema", "emails", "main_branch", "calendar", "points_as_hours", "cache_ttl", "in_progress", *TRACKERS}
IN_PROGRESS = ["in progress", "in development", "doing", "started", "в работе"]
_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    root: Path
    emails: list[str] = field(default_factory=list)
    main_branch: str | None = None
    calendar: Calendar = field(default_factory=Calendar)
    trackers: dict[str, dict] = field(default_factory=dict)
    points_as_hours: float | None = None
    cache_ttl: int = 3600
    in_progress: list[str] = field(default_factory=lambda: list(IN_PROGRESS))
    warnings: list[str] = field(default_factory=list)
    path: Path | None = None

    def token(self, tracker: str) -> str | None:
        section = self.trackers.get(tracker, {})
        if section.get("token"):
            return str(section["token"])
        return os.environ.get(str(section.get("token_env") or TOKEN_ENV[tracker])) or None


def load(root: Path, git_email: str | None = None) -> Config:
    path = root / CONFIG_NAME
    if not path.is_file():
        return parse({}, root, git_email)
    text = path.read_text(encoding="utf-8")
    if _PEM.search(text):
        raise ConfigError(f"{CONFIG_NAME} contains a private key. fibo never needs one — remove it.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{CONFIG_NAME}: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{CONFIG_NAME}: expected a JSON object")
    return parse(data, root, git_email, path)


def _hour(value: object, name: str) -> float:
    if isinstance(value, (int, float)) and 0 <= value <= 24:
        return float(value)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value))
    if m and int(m.group(1)) <= 24 and int(m.group(2)) < 60:
        return int(m.group(1)) + int(m.group(2)) / 60
    raise ConfigError(f"calendar.{name}: expected an hour like 9 or \"09:00\", got {value!r}")


def _calendar(data: object) -> Calendar:
    if data is None:
        return Calendar()
    if not isinstance(data, dict):
        raise ConfigError("calendar: expected an object")
    days = data.get("workdays", [0, 1, 2, 3, 4])
    try:
        workdays = frozenset(_DAYS[str(d).lower()[:3]] if isinstance(d, str) else int(d) for d in days)
    except (KeyError, ValueError, TypeError):
        raise ConfigError(f"calendar.workdays: expected names like \"mon\" or numbers 0-6, got {days!r}") from None
    if not workdays or not workdays <= set(range(7)):
        raise ConfigError("calendar.workdays: at least one day, 0 (Monday) to 6 (Sunday)")
    start, end = _hour(data.get("start", 9), "start"), _hour(data.get("end", 18), "end")
    if end <= start:
        raise ConfigError("calendar: the working day has to end after it starts")
    per_day = data.get("hours_per_day", 8)
    if not isinstance(per_day, (int, float)) or not 0 < per_day <= end - start:
        raise ConfigError("calendar.hours_per_day: a positive number no longer than the working window")
    return Calendar(workdays, start, end, float(per_day))


def parse(data: dict, root: Path, git_email: str | None = None, path: Path | None = None) -> Config:
    cfg = Config(root=root, path=path)
    for key in data:
        if key not in KNOWN:
            cfg.warnings.append(f"{CONFIG_NAME}: unknown key '{key}' ignored")

    emails = data.get("emails", [])
    if isinstance(emails, str):
        emails = [emails]
    if not isinstance(emails, list) or not all(isinstance(e, str) and "@" in e for e in emails):
        raise ConfigError("emails: expected a list of your email addresses")
    cfg.emails = list(dict.fromkeys(e.strip().lower() for e in ([git_email] if git_email else []) + emails))

    main = data.get("main_branch")
    if main is not None and not isinstance(main, str):
        raise ConfigError("main_branch: expected a branch name")
    cfg.main_branch = main
    cfg.calendar = _calendar(data.get("calendar"))

    pah = data.get("points_as_hours")
    if pah is not None and (not isinstance(pah, (int, float)) or pah <= 0):
        raise ConfigError("points_as_hours: expected a positive number of hours per point")
    cfg.points_as_hours = float(pah) if pah is not None else None

    ttl = data.get("cache_ttl", 3600)
    if not isinstance(ttl, int) or ttl < 0:
        raise ConfigError("cache_ttl: expected seconds, 0 or more")
    cfg.cache_ttl = ttl

    statuses = data.get("in_progress")
    if statuses is not None:
        if not isinstance(statuses, list) or not all(isinstance(s, str) for s in statuses):
            raise ConfigError("in_progress: expected a list of status names")
        cfg.in_progress = [s.lower() for s in statuses]

    for name in TRACKERS:
        section = data.get(name)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise ConfigError(f"{name}: expected an object")
        clean = {}
        for key, value in section.items():
            if key.endswith(("_file", "_path")) or key in {"key", "private_key", "keyfile", "ssh_key"}:
                cfg.warnings.append(f"{name}.{key} ignored: secrets come from this file or the environment, never from a path")
                continue
            clean[key] = value
        cfg.trackers[name] = clean
    return cfg
