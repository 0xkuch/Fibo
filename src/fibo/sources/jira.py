"""Jira: `timeoriginalestimate`, and the changelog that says when it was set.

Only your issues (assignee = currentUser()). Only reads. Cloud uses the
enhanced search endpoint; Server and Data Center fall back to the classic one.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

from ..config import Config
from ..model import Task, from_seconds, parse_time
from .http import Cache, Client, SourceError, Transport

FIELDS = "summary,status,resolutiondate,created,timeoriginalestimate,issuetype,labels"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def fetch(section: dict, cfg: Config, cache: Cache | None = None, transport: Transport | None = None) -> list[Task]:
    base = str(section.get("url", "")).rstrip("/")
    if not base:
        raise SourceError("jira: set jira.url in .fibo.json (https://yours.atlassian.net)")
    token = cfg.token("jira")
    if not token:
        raise SourceError("jira: no token — set JIRA_API_TOKEN, or name another variable in jira.token_env")
    email = section.get("email")
    auth = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode() if email else f"Bearer {token}"
    api = Client("jira", {"Authorization": auth}, cache, transport)
    per_day, per_week = _timetracking(api, base)
    jql = "assignee = currentUser()"
    if section.get("jql"):
        jql += f" AND ({section['jql']})"
    jql += " ORDER BY created ASC"
    statuses = set(cfg.in_progress)
    return [_task(api, base, issue, per_day, per_week, statuses) for issue in _search(api, base, jql)]


def _timetracking(api: Client, base: str) -> tuple[float, float]:
    """Jira's own idea of a day and a week, so "1d" means what it meant when it was typed."""
    try:
        opts = api.get(f"{base}/rest/api/3/configuration/timetracking/options")
        return float(opts.get("workingHoursPerDay") or 8), float(opts.get("workingDaysPerWeek") or 5)
    except (SourceError, AttributeError, TypeError, ValueError):
        return 8.0, 5.0


def _search(api: Client, base: str, jql: str) -> list[dict]:
    params = {"jql": jql, "fields": FIELDS, "expand": "changelog", "maxResults": 100}
    issues: list[dict] = []
    token = None
    try:
        while True:
            page = api.get(f"{base}/rest/api/3/search/jql", {**params, "nextPageToken": token})
            issues += page.get("issues", [])
            token = page.get("nextPageToken")
            if not token or page.get("isLast"):
                return issues
    except SourceError as exc:
        if issues or exc.status not in (404, 405, 410):
            raise
    start = 0
    while True:
        page = api.get(f"{base}/rest/api/2/search", {**params, "startAt": start})
        batch = page.get("issues", [])
        issues += batch
        start += len(batch)
        if not batch or start >= int(page.get("total", 0)):
            return issues


def _histories(api: Client, base: str, issue: dict) -> list[dict]:
    log = issue.get("changelog") or {}
    histories = list(log.get("histories") or [])
    if int(log.get("total") or 0) > len(histories):  # search truncates long changelogs
        key = issue["key"]
        try:
            histories, start = [], 0
            while True:
                page = api.get(f"{base}/rest/api/3/issue/{key}/changelog", {"startAt": start, "maxResults": 100})
                values = page.get("values", [])
                histories += values
                start += len(values)
                if not values or page.get("isLast", True):
                    break
        except SourceError:
            full = api.get(f"{base}/rest/api/2/issue/{key}", {"expand": "changelog", "fields": "created"})
            histories = (full.get("changelog") or {}).get("histories", [])
    return sorted(histories, key=lambda h: parse_time(h.get("created")) or EPOCH)


def _task(api: Client, base: str, issue: dict, per_day: float, per_week: float, statuses: set[str]) -> Task:
    f = issue.get("fields") or {}
    key = issue["key"]
    url = f"{base}/browse/{key}"
    created = parse_time(f.get("created"))
    events: list[tuple[datetime | None, object]] = []
    started = None
    for h in _histories(api, base, issue):
        at = parse_time(h.get("created"))
        for item in h.get("items") or []:
            name = str(item.get("fieldId") or item.get("field") or "").lower()
            if name == "timeoriginalestimate":
                if not events and item.get("from"):  # the value the issue was created with
                    events.append((created, item["from"]))
                events.append((at, item.get("to")))
            elif name == "status" and started is None and str(item.get("toString", "")).lower() in statuses:
                started = at
    if not events and f.get("timeoriginalestimate"):
        events.append((created, f["timeoriginalestimate"]))
    estimates = [from_seconds(v, "jira", at, url, per_day, per_week) for at, v in events if v not in (None, "", "0", 0)]
    return Task(key, "jira", f.get("summary") or "", url, tuple(f.get("labels") or ()),
                (f.get("issuetype") or {}).get("name", ""), created, started,
                parse_time(f.get("resolutiondate")), estimates)
