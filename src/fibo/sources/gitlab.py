"""GitLab: `time_estimate`, and the system note that says when it was set."""

from __future__ import annotations

import re
import urllib.parse

from .. import git
from ..config import Config
from ..model import Task, from_seconds, parse_estimate, parse_time
from .http import Cache, Client, SourceError, Transport

_NOTE = re.compile(r"changed time estimate to (.+?)\s*$", re.IGNORECASE)


def project(section: dict, cfg: Config) -> str:
    if section.get("project"):
        return str(section["project"])
    host = urllib.parse.urlsplit(str(section.get("url", "https://gitlab.com"))).netloc
    m = re.search(rf"{re.escape(host)}[:/](.+?)(?:\.git)?/?$", git.remote_url(cfg.root) or "")
    if not m:
        raise SourceError("gitlab: set gitlab.project (group/name or id) in .fibo.json")
    return m.group(1)


def fetch(section: dict, cfg: Config, cache: Cache | None = None, transport: Transport | None = None) -> list[Task]:
    token = cfg.token("gitlab")
    if not token:
        raise SourceError("gitlab: no token — set GITLAB_TOKEN, or name another variable in gitlab.token_env")
    root = str(section.get("url", "https://gitlab.com")).rstrip("/") + "/api/v4"
    pid = urllib.parse.quote(project(section, cfg), safe="")
    api = Client("gitlab", {"PRIVATE-TOKEN": token}, cache, transport)
    me = api.get(f"{root}/user")
    issues = _pages(api, f"{root}/projects/{pid}/issues",
                    {"assignee_id": me["id"], "scope": "all", "state": "all"})
    return [_issue(api, root, pid, it) for it in issues]


def _pages(api: Client, url: str, params: dict, limit: int = 50) -> list[dict]:
    out = []
    for page in range(1, limit + 1):
        batch = api.get(url, {**params, "per_page": 100, "page": page})
        out += batch
        if len(batch) < 100:
            break
    return out


def _issue(api: Client, root: str, pid: str, it: dict) -> Task:
    created, url = parse_time(it.get("created_at")), it.get("web_url", "")
    seconds = (it.get("time_stats") or {}).get("time_estimate") or 0
    estimates = []
    if seconds:
        notes = _pages(api, f"{root}/projects/{pid}/issues/{it['iid']}/notes",
                       {"sort": "asc", "order_by": "created_at"}, limit=5)
        for note in notes:
            m = _NOTE.search(note.get("body", "")) if note.get("system") else None
            if m:
                estimates.append(parse_estimate(m.group(1), "gitlab", parse_time(note.get("created_at")), url))
        if not estimates:
            estimates.append(from_seconds(seconds, "gitlab", created, url))
    return Task(f"#{it['iid']}", "gitlab", it.get("title") or "", url, tuple(it.get("labels") or ()),
                it.get("issue_type") or "", created, None, parse_time(it.get("closed_at")), estimates)
