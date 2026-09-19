"""GitHub: `est: 2d` labels on your issues, estimates in your pull request bodies,
and (if you name it) an estimate field in Projects.

A label's time is the moment it was applied, read from the issue's events,
so a label added after the first commit is refused like any late estimate.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .. import git
from ..config import Config
from ..model import Estimate, Task, parse_estimate, parse_time
from . import convention
from .http import Cache, Client, SourceError, Transport

API = "https://api.github.com"
_LABEL = re.compile(r"^\s*(?:est|estimate)\s*[:=]?\s*(\S.*?)\s*$", re.IGNORECASE)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
PROJECT_QUERY = """
query Items($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 50, after: $after) {
    nodes { ... on Issue { number projectItems(first: 10) { nodes { fieldValues(first: 30) { nodes {
      ... on ProjectV2ItemFieldTextValue { text updatedAt field { ... on ProjectV2FieldCommon { name } } }
      ... on ProjectV2ItemFieldNumberValue { number updatedAt field { ... on ProjectV2FieldCommon { name } } }
      ... on ProjectV2ItemFieldSingleSelectValue { name updatedAt field { ... on ProjectV2FieldCommon { name } } }
    } } } } } }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def slug(section: dict, cfg: Config) -> str:
    if section.get("repo"):
        return str(section["repo"])
    m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$", git.remote_url(cfg.root) or "")
    if not m:
        raise SourceError("github: set github.repo (owner/name) in .fibo.json")
    return m.group(1)


def fetch(section: dict, cfg: Config, cache: Cache | None = None, transport: Transport | None = None) -> list[Task]:
    token = cfg.token("github")
    if not token:
        raise SourceError("github: no token — set GITHUB_TOKEN, or name another variable in github.token_env")
    base = str(section.get("api", API)).rstrip("/")
    api = Client("github", {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                            "X-GitHub-Api-Version": "2022-11-28"}, cache, transport)
    repo = slug(section, cfg)
    login = api.get(f"{base}/user")["login"]
    tasks = [_issue(api, base, repo, item) for item in _pages(api, f"{base}/repos/{repo}/issues",
                                                             {"assignee": login, "state": "all"})
             if "pull_request" not in item]
    for page in range(1, 11):  # the search API stops at 1000 results
        found = api.get(f"{base}/search/issues", {"q": f"repo:{repo} is:pr author:{login}", "per_page": 100,
                                                  "page": page}).get("items", [])
        for pr in found:
            said = convention.from_text(pr.get("body"), parse_time(pr.get("created_at")), pr.get("html_url", ""),
                                        "github")
            if said:
                tasks.append(Task(f"PR #{pr['number']}", "github", pr.get("title") or "", pr.get("html_url", ""),
                                  created=parse_time(pr.get("created_at")), estimates=said, pr=str(pr["number"])))
        if len(found) < 100:
            break
    if section.get("project_field"):
        _project_field(api, base, repo, str(section["project_field"]), str(section.get("project_field_unit", "h")),
                       tasks)
    return tasks


def _pages(api: Client, url: str, params: dict) -> list[dict]:
    out, page = [], 1
    while True:
        batch = api.get(url, {**params, "per_page": 100, "page": page})
        out += batch
        if len(batch) < 100:
            return out
        page += 1


def _issue(api: Client, base: str, repo: str, item: dict) -> Task:
    number, url = item["number"], item.get("html_url", "")
    names = [l["name"] if isinstance(l, dict) else str(l) for l in item.get("labels", [])]
    estimates: list[Estimate] = []
    if any(_LABEL.match(n) for n in names):
        # Every estimate label ever applied, in order — removed ones included.
        for ev in _pages(api, f"{base}/repos/{repo}/issues/{number}/events", {}):
            label = (ev.get("label") or {}).get("name", "")
            m = _LABEL.match(label)
            if ev.get("event") == "labeled" and m:
                estimates.append(parse_estimate(m.group(1), "github", parse_time(ev.get("created_at")), url))
        estimates.sort(key=lambda e: e.at or EPOCH)
    return Task(f"#{number}", "github", item.get("title") or "", url,
                tuple(n for n in names if not _LABEL.match(n)), "", parse_time(item.get("created_at")), None,
                parse_time(item.get("closed_at")), estimates)


def _project_field(api: Client, base: str, repo: str, field: str, unit: str, tasks: list[Task]) -> None:
    """Projects keep no history of a field, only when it last changed: that time is used, conservatively."""
    graphql = base[: -len("/v3")] + "/graphql" if base.endswith("/api/v3") else f"{base}/graphql"
    by_key = {t.key: t for t in tasks}
    after = None
    while True:
        data = api.graphql(graphql, PROJECT_QUERY, {"q": f"repo:{repo} is:issue assignee:@me", "after": after})
        for node in data["search"]["nodes"]:
            task = by_key.get(f"#{node.get('number')}")
            for item in ((node.get("projectItems") or {}).get("nodes") or []):
                for value in ((item.get("fieldValues") or {}).get("nodes") or []):
                    if task is None or str((value.get("field") or {}).get("name", "")).lower() != field.lower():
                        continue
                    raw = value.get("text") or value.get("name") or (
                        f"{value['number']:g}{unit}" if value.get("number") is not None else "")
                    if raw:
                        task.estimates.append(parse_estimate(raw, "github", parse_time(value.get("updatedAt")),
                                                             task.url))
        info = data["search"]["pageInfo"]
        if not info["hasNextPage"]:
            return
        after = info["endCursor"]
